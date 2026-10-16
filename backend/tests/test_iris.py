from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import httpx
import pytest

from rakathon_backend.b2.iris.config import IrisFhirConfig, IrisSqlConfig, VectorStoreConfig
from rakathon_backend.b2.iris.fhir import DirectFhirAdapter
from rakathon_backend.b2.iris.sql import IrisSqlStore
from rakathon_backend.b2.iris.storage import CompositeIrisStorage
from rakathon_backend.common.errors import ContractError

BASE = "http://127.0.0.1:8765/fhir/r4"


def _fhir(handler: Callable[[httpx.Request], httpx.Response]) -> DirectFhirAdapter:
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=BASE,
        trust_env=False,
        follow_redirects=False,
    )
    return DirectFhirAdapter(
        IrisFhirConfig(base_url=BASE, username="u", password="p"), client=client
    )


def test_fhir_read_ok() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        return httpx.Response(200, json={"resourceType": "Patient", "id": "p1"})

    found = _fhir(handler).read("Patient", "p1")
    assert found is not None and found["id"] == "p1"
    assert calls == ["GET /fhir/r4/Patient/p1"]


def test_fhir_read_404_is_none() -> None:
    adapter = _fhir(lambda request: httpx.Response(404, json={}))
    assert adapter.read("Patient", "gone") is None


def test_fhir_html_error_redacted() -> None:
    body = b"<html>secret-marker-xyz behind login</html>"

    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(401, content=body)

    with pytest.raises(ContractError) as excinfo:
        _fhir(handler).read("Patient", "p1")
    assert excinfo.value.code == "auth_failed"
    assert "secret-marker-xyz" not in excinfo.value.message


def test_fhir_traversal_never_hits_network() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={})

    adapter = _fhir(handler)
    with pytest.raises(ContractError):
        adapter.read("Patient", "../evil")
    with pytest.raises(ContractError):
        adapter.read("Nope", "p1")
    with pytest.raises(ContractError):
        adapter.search("Patient", {"weird key!": "x"})
    assert calls == []


def test_fhir_search_parses_and_rejects_paging() -> None:
    bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [{"resource": {"resourceType": "Patient", "id": "a"}}],
        "link": [{"relation": "next", "url": "https://iris.example/fhir/r4?page=2"}],
    }
    adapter = _fhir(lambda request: httpx.Response(200, json=bundle))
    with pytest.raises(ContractError) as excinfo:
        adapter.search("Patient", {})
    assert excinfo.value.code == "truncated"


def test_fhir_write_put_idempotent() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["ctype"] = request.headers.get("content-type", "")
        return httpx.Response(200, json={"resourceType": "Task", "id": "t1"})

    stored = _fhir(handler).write({"resourceType": "Task", "id": "t1"})
    assert stored["id"] == "t1"
    assert seen == {
        "method": "PUT",
        "path": "/fhir/r4/Task/t1",
        "ctype": "application/fhir+json",
    }


def test_fhir_transaction_inspects_entries() -> None:
    ok_bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "request": {"method": "POST", "url": "Patient/p1"},
                "resource": {"resourceType": "Patient", "id": "p1"},
            }
        ],
    }

    def ok(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "type": "transaction-response",
                "entry": [{"response": {"status": "201 Created"}}],
            },
        )

    out = _fhir(ok).transaction(ok_bundle)
    assert out["type"] == "transaction-response"

    def bad(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "type": "transaction-response",
                "entry": [{"response": {"status": "400 Bad Request"}}],
            },
        )

    with pytest.raises(ContractError):
        _fhir(bad).transaction(ok_bundle)


class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Any]]] = []
        self.rows: list[tuple[Any, ...]] = []
        self.rowcount = 1

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        self.calls.append((sql, list(params or [])))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self.rows)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None


class FakeConn:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.committed = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


def _sql_config() -> IrisSqlConfig:
    return IrisSqlConfig(host="127.0.0.1", port=1972, namespace="NS", username="u", password="p")


def _task() -> dict[str, Any]:
    return {
        "id": "task-1",
        "ownerId": "nurse",
        "dueAt": "2030-01-01T00:00:00+00:00",
        "status": "OPEN",
        "requiredAckUserIds": ["nurse"],
        "acknowledgedBy": [],
        "patientRef": "Patient/p1",
        "version": 1,
    }


def test_sql_tasks_write_uses_bound_params() -> None:
    cursor = FakeCursor()
    cursor.rowcount = 0
    store = IrisSqlStore(_sql_config(), tasks_factory=lambda: FakeConn(cursor))
    store.tasks_write(_task())
    assert len(cursor.calls) == 2
    for sql, params in cursor.calls:
        assert "?" in sql
        assert "task-1" not in sql
    assert cursor.calls[1][1][0] == "task-1"


def test_sql_tasks_read_and_ack() -> None:
    cursor = FakeCursor()
    cursor.rows = [
        ("task-1", "nurse", "2030-01-01T00:00:00+00:00", "OPEN", '["nurse"]', "[]", "Patient/p1", 1)
    ]
    store = IrisSqlStore(_sql_config(), tasks_factory=lambda: FakeConn(cursor))
    items = store.tasks_read("task-1")
    assert items[0]["ownerId"] == "nurse"
    assert "WHERE id = ?" in cursor.calls[0][0]
    assert store.tasks_read(None)[0]["id"] == "task-1"
    assert store.tasks_ack("task-1", "nurse")["status"] == "ACKED"
    empty = FakeCursor()
    missing = IrisSqlStore(_sql_config(), tasks_factory=lambda: FakeConn(empty))
    with pytest.raises(KeyError):
        missing.tasks_ack("gone", "nurse")


def test_sql_vector_anon_binding_and_dims() -> None:
    cursor = FakeCursor()
    cursor.rows = [("v1", "{}")]
    anon = VectorStoreConfig(enabled=True, schema="ANON", table="VEC", dimensions=2)
    store = IrisSqlStore(
        _sql_config(),
        tasks_factory=lambda: FakeConn(FakeCursor()),
        anon_factory=lambda: FakeConn(cursor),
        anon=anon,
    )
    hits = store.vector_search("anonymized", "[0.1, 0.2]", 5)
    assert hits == [{"vectorId": "v1", "synthetic": True}]
    sql, params = cursor.calls[0]
    assert "VECTOR_COSINE" in sql and "TO_VECTOR(?, FLOAT)" in sql and "DESC" in sql
    assert params == ["0.1,0.2"]
    with pytest.raises(ContractError):
        store.vector_search("anonymized", "[0.1]", 5)


def test_sql_vector_disabled_and_isolation() -> None:
    store = IrisSqlStore(_sql_config(), tasks_factory=lambda: FakeConn(FakeCursor()))
    with pytest.raises(LookupError):
        store.vector_search("anonymized", "[0.1]", 5)
    with pytest.raises(LookupError):
        store.vector_search("patient", "[0.1]", 5)


def test_composite_patient_vector_resolves_fhir() -> None:
    anon_calls: list[str] = []

    def anon_factory() -> FakeConn:
        anon_calls.append("anon")
        return FakeConn(FakeCursor())

    patient_cursor = FakeCursor()
    patient_cursor.rows = [("Patient", "p1")]
    patient = VectorStoreConfig(enabled=True, schema="H", table="V", dimensions=2)
    sql = IrisSqlStore(
        _sql_config(),
        tasks_factory=lambda: FakeConn(FakeCursor()),
        anon_factory=anon_factory,
        patient_factory=lambda: FakeConn(patient_cursor),
        anon=VectorStoreConfig(enabled=False, schema="", table="", dimensions=0),
        patient=patient,
    )
    fhir = _fhir(lambda request: httpx.Response(200, json={"resourceType": "Patient", "id": "p1"}))
    composite = CompositeIrisStorage(fhir, sql)
    hits = composite.vector_search("patient", "[0.1, 0.2]", 5)
    assert hits[0]["resource"]["id"] == "p1"
    assert anon_calls == []


def test_sql_schema_discovery_standard_views() -> None:
    cursor = FakeCursor()
    cursor.rows = [("FSB", "Tasks")]
    store = IrisSqlStore(_sql_config(), tasks_factory=lambda: FakeConn(cursor))
    tables = store.schema_discover({"kind": "tables"})
    assert tables["tables"] == [{"schema": "FSB", "table": "Tasks"}]
    assert "INFORMATION_SCHEMA.TABLES" in cursor.calls[0][0]
    cursor.rows = [("id", "VARCHAR")]
    columns = store.schema_discover({"kind": "columns", "schema": "FSB", "table": "Tasks"})
    assert columns["columns"] == [{"name": "id", "type": "VARCHAR"}]
    with pytest.raises(ContractError):
        store.schema_discover({"kind": "columns", "schema": "weird!", "table": "T"})


def test_sql_missing_driver_is_not_configured() -> None:
    store = IrisSqlStore(_sql_config())
    with pytest.raises(ContractError) as excinfo:
        store.tasks_write(_task())
    assert excinfo.value.code == "not_configured"


def test_iris_config_gates() -> None:
    with pytest.raises(ContractError):
        IrisFhirConfig.from_env({})
    with pytest.raises(ContractError):
        IrisFhirConfig.from_env(
            {
                "RAKATHON_IRIS_FHIR_BASE_URL": "http://plain.example/fhir",
                "RAKATHON_IRIS_FHIR_USER": "u",
                "RAKATHON_IRIS_FHIR_PASSWORD": "p",
            }
        )
    with pytest.raises(ContractError):
        IrisSqlConfig.from_env(
            {
                "RAKATHON_IRIS_SQL_HOST": "127.0.0.1",
                "RAKATHON_IRIS_SQL_PORT": "443",
                "RAKATHON_IRIS_SQL_NAMESPACE": "NS",
                "RAKATHON_IRIS_SQL_USER": "u",
                "RAKATHON_IRIS_SQL_PASSWORD": "p",
            }
        )
    with pytest.raises(ContractError):
        IrisSqlConfig.from_env(
            {
                "RAKATHON_IRIS_SQL_HOST": "db.example",
                "RAKATHON_IRIS_SQL_PORT": "1972",
                "RAKATHON_IRIS_SQL_NAMESPACE": "NS",
                "RAKATHON_IRIS_SQL_USER": "u",
                "RAKATHON_IRIS_SQL_PASSWORD": "p",
            }
        )
