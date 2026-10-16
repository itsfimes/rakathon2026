from __future__ import annotations

import csv
import tracemalloc
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.b2.iris.config import IrisSqlConfig
from rakathon_backend.b2.iris.screening_sql import ScreeningSqlStore
from rakathon_backend.b2.screening import schema
from rakathon_backend.b2.screening.archive import ArchiveScreeningStore
from rakathon_backend.b2.screening.reader import resolve_source, validate_source
from rakathon_backend.b2.service import B2Service
from rakathon_backend.bridge.crypto import BridgeCrypto, generate_key_file, load_key
from rakathon_backend.bridge.protocol import check_arguments, check_operation
from rakathon_backend.bridge.replay import ReplayCache
from rakathon_backend.bridge.server import BridgeDispatcher
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.kinds import request_kind
from rakathon_backend.common.rpc import new_envelope


def _row(inv: str, person: str, **over: str) -> dict[str, str]:
    base = {name: "" for name in schema.HEADER}
    base.update(
        {
            "INVITATION_ID": inv,
            "PERSON_ID": person,
            "INVITATION_DATE": "14.01.2020",
            "AGE_BAND": "65-69",
            "VZP_TERRITORIAL_AREA": "PRAHA",
            "PRIOR_INVITATION_COUNT": "0",
            "INVITATION_SEQUENCE": "1",
            "FIRST_INVITATION": "A",
            "GP_REGISTERED": "N",
            "GP_REG_DURATION_BAND": "",
            "GYN_REGISTERED_FLAG": "N",
            "GYN_REG_DURATION_BAND": "",
            "NEVER_SCREENED_BEFORE_FLAG": "A",
            "SCREENING_3M_FLAG": "N",
            "SCREENING_6M_FLAG": "N",
            "SCREENING_12M_FLAG": "N",
        }
    )
    base.update(over)
    return base


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(schema.HEADER))
        writer.writeheader()
        writer.writerows(rows)


class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Any]]] = []
        self.rows: list[tuple[Any, ...]] = []
        self.rowcount = 1
        self.fail_on: str = ""

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("boom")
        self.calls.append((sql, list(params or [])))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self.rows)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None


class FakeConn:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        return None


def _config() -> IrisSqlConfig:
    return IrisSqlConfig(host="127.0.0.1", port=1972, namespace="NS", username="u", password="p")


def _store(cursor: FakeCursor) -> ScreeningSqlStore:
    return ScreeningSqlStore(_config(), factory=lambda: FakeConn(cursor))


def test_init_db_ddl() -> None:
    cursor = FakeCursor()
    result = _store(cursor).init_db()
    assert result["status"] == "created"
    assert "CREATE TABLE" in cursor.calls[0][0]
    assert "PRIMARY KEY (INVITATION_ID)" in cursor.calls[0][0]


def test_import_batch_insert_bound_params() -> None:
    cursor = FakeCursor()
    cursor.rows = []
    out = _store(cursor).import_batch([_row("INV1", "111")])
    assert out == {"imported": 1, "skipped": 0, "total": 1}
    insert = [c for c in cursor.calls if c[0].startswith("INSERT")]
    assert len(insert) == 1
    assert "?" in insert[0][0] and "INV1" not in insert[0][0]


def test_import_idempotent_skip_identical() -> None:
    cursor = FakeCursor()
    record = _row("INV1", "111")
    cursor.rows = [tuple(record[name] for name in schema.HEADER)]
    out = _store(cursor).import_batch([dict(record)])
    assert out == {"imported": 0, "skipped": 1, "total": 1}
    assert not [c for c in cursor.calls if c[0].startswith("INSERT")]


def test_import_conflict_rolls_back() -> None:
    cursor = FakeCursor()
    record = _row("INV1", "111")
    stored = dict(record)
    stored["AGE_BAND"] = "70-74"
    cursor.rows = [tuple(stored[name] for name in schema.HEADER)]
    conns: list[FakeConn] = []

    def factory() -> FakeConn:
        conn = FakeConn(cursor)
        conns.append(conn)
        return conn

    store = ScreeningSqlStore(_config(), factory=factory)
    with pytest.raises(ContractError) as excinfo:
        store.import_batch([record])
    assert excinfo.value.code == "conflict"
    assert conns[0].rolled_back is True and conns[0].committed is False


def test_import_rejects_bad_rows_and_batch_caps() -> None:
    cursor = FakeCursor()
    bad = _row("INV1", "111")
    bad["GP_REGISTERED"] = "Y"
    with pytest.raises(ContractError):
        _store(cursor).import_batch([bad])
    with pytest.raises(ContractError):
        _store(cursor).import_batch([])
    with pytest.raises(ContractError):
        _store(cursor).import_batch([_row(f"INV{i}", "1") for i in range(501)])


def test_query_bound_top_and_offset() -> None:
    cursor = FakeCursor()
    record = _row("INV1", "111")
    cursor.rows = [tuple(record[name] for name in schema.HEADER)] * 3
    out = _store(cursor).query({}, ["INVITATION_ID"], 2, 1)
    assert len(out) == 2 and out[0]["INVITATION_ID"] == "INV1"
    sql, params = cursor.calls[0]
    assert "SELECT TOP 3" in sql and "INV1" not in sql and params == []
    filtered = _store(cursor).query({"PERSON_ID": "111"}, ["INVITATION_ID"], 10, 0)
    assert len(filtered) == 3
    assert "PERSON_ID = ?" in cursor.calls[-1][0]
    assert cursor.calls[-1][1] == ["111"]
    with pytest.raises(ContractError):
        _store(cursor).query({}, None, 10, 5001)


def test_bridge_protocol_screening_args() -> None:
    assert check_operation("screening.import") == "screening.import"
    assert check_operation("screening.query") == "screening.query"
    args = check_arguments("screening.import", {"rows": [_row("INV1", "111")]})
    assert len(args["rows"]) == 1
    with pytest.raises(ContractError):
        check_arguments("screening.import", {"rows": []})
    with pytest.raises(ContractError):
        check_arguments("screening.query", {"filters": {"nope": "x"}, "limit": 10, "offset": 0})
    qargs = check_arguments(
        "screening.query",
        {"filters": {"PERSON_ID": "111"}, "projection": ["INVITATION_ID"], "limit": 5, "offset": 0},
    )
    assert qargs["limit"] == 5


class FakeScreening:
    def __init__(self) -> None:
        self.rows = [_row("INV1", "111")]

    def import_batch(self, rows: list[dict[str, str]]) -> dict[str, int]:
        return {"imported": len(rows), "skipped": 0, "total": len(rows)}

    def query(
        self, filters: dict[str, str], projection: list[str] | None, limit: int, offset: int
    ) -> list[dict[str, str]]:
        _ = (filters, projection, offset)
        return self.rows[:limit]


def _dispatcher(
    screening: Any | None, workdir: Path, name: str = "screen-test.key"
) -> tuple[BridgeDispatcher, BridgeCrypto]:
    key_file = workdir / name
    generate_key_file(key_file)
    key = load_key(key_file)
    crypto = BridgeCrypto(key=key, key_id="test-key", ttl=60)
    dispatcher = BridgeDispatcher(crypto, object(), ReplayCache(), screening=screening)
    return (dispatcher, crypto)


def test_bridge_screening_roundtrip_and_unconfigured(tmp_path: Path) -> None:
    dispatcher, crypto = _dispatcher(FakeScreening(), tmp_path)
    rid, token = crypto.encrypt_request("screening.query", {"filters": {}, "limit": 5, "offset": 0})
    status, payload, _ = dispatcher.handle_outer({"keyId": "test-key", "token": token})
    assert status == 200
    out = crypto.decrypt_response(payload["token"], rid, "screening.query")
    assert len(out["rows"]) == 1
    rid2, token2 = crypto.encrypt_request("screening.import", {"rows": [_row("INV9", "999")]})
    status2, payload2, _ = dispatcher.handle_outer({"keyId": "test-key", "token": token2})
    assert status2 == 200
    done = crypto.decrypt_response(payload2["token"], rid2, "screening.import")
    assert done == {"imported": 1, "skipped": 0, "total": 1}
    naked = BridgeDispatcher(crypto, object(), ReplayCache(), screening=None)
    rid3, token3 = crypto.encrypt_request(
        "screening.query", {"filters": {}, "limit": 5, "offset": 0}
    )
    _, payload3, _ = naked.handle_outer({"keyId": "test-key", "token": token3})
    with pytest.raises(ContractError) as excinfo:
        crypto.decrypt_response(payload3["token"], rid3, "screening.query")
    assert excinfo.value.code == "not_configured"


async def test_b2_screening_query_and_unconfigured(tmp_path: Path) -> None:
    target = tmp_path / "q.csv"
    _write_csv(target, [_row("INV1", "111")])
    store = ArchiveScreeningStore(resolve_source(str(target)))

    async def allow(*, user_id: str, action: str, correlation_id: str) -> bool:
        _ = (user_id, action, correlation_id)
        return True

    service = B2Service(store=FakeStorage(), auth_check=allow, screening=store)
    request = new_envelope(
        source="b4",
        target="b2",
        action="screening.query",
        data_kind=DataKind.METADATA,
        payload={"filters": {"PERSON_ID": "111"}, "limit": 10, "offset": 0},
        user_id="admin",
    )
    reply = await service.handle(request)
    assert reply.data_kind == DataKind.PROPRIETARY
    assert reply.payload["count"] == 1
    denied = B2Service(store=FakeStorage(), auth_check=allow)
    with pytest.raises(ContractError) as excinfo:
        await denied.handle(request)
    assert excinfo.value.code == "not_configured"


class FakeStorage:
    def fhir_write(self, resource: dict[str, Any]) -> dict[str, Any]:
        return dict(resource)

    def fhir_transaction(self, bundle: dict[str, Any]) -> dict[str, Any]:
        return dict(bundle)

    def fhir_read(self, resource_type: str, rid: str) -> dict[str, Any] | None:
        _ = (resource_type, rid)
        return None

    def fhir_search(self, resource_type: str, params: dict[str, str]) -> list[dict[str, Any]]:
        _ = (resource_type, params)
        return []

    def tasks_create(self, task: dict[str, Any]) -> dict[str, Any]:
        return dict(task)

    def tasks_write(self, task: dict[str, Any]) -> dict[str, Any]:
        return dict(task)

    def tasks_read(self, task_id: str | None = None) -> list[dict[str, Any]]:
        _ = task_id
        return []

    def tasks_ack(self, task_id: str, user_id: str) -> dict[str, Any]:
        _ = (task_id, user_id)
        raise KeyError(task_id)

    def vector_search(self, channel: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        _ = (channel, query, limit)
        return []


def test_memory_bounded_stream(tmp_path: Path) -> None:
    target = tmp_path / "big.csv"
    with open(target, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(schema.HEADER))
        writer.writeheader()
        for i in range(50000):
            writer.writerow(_row(f"INV{i:012d}", f"{100000000000000 + i}"))
    tracemalloc.start()
    try:
        result = validate_source(explicit=str(target))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result.rows == 50000
    assert peak < 120 * 1024 * 1024


def test_envelope_kinds_for_screening() -> None:
    assert request_kind("screening.query") == DataKind.METADATA
    assert request_kind("fhir.search") == DataKind.METADATA
    env = Envelope(
        request_id="r",
        correlation_id="c",
        source="b4",
        target="b2",
        action="screening.query",
        data_kind=DataKind.METADATA,
        payload={},
    )
    assert env.action == "screening.query"
