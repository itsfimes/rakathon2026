from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import Any

import pytest

from rakathon_backend.b2.iris import task_sql
from rakathon_backend.b2.iris.config import (
    IrisSqlConfig,
    VectorStoreConfig,
    vector_sql_configs,
)
from rakathon_backend.b2.iris.sql import IrisSqlStore
from rakathon_backend.common.errors import ContractError


class FakeCursor:
    def __init__(
        self,
        rows: list[tuple[Any, ...]] | None = None,
        rowcounts: list[int] | None = None,
        fail_on: tuple[str, ...] = (),
        leak: str = "",
    ) -> None:
        self._rows = list(rows or [])
        self._rowcounts = list(rowcounts if rowcounts is not None else [1])
        self._fail_on = fail_on
        self._leak = leak
        self.calls: list[tuple[str, list[Any]]] = []
        self.rowcount = 1

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        self.calls.append((sql, list(params or [])))
        for key in self._fail_on:
            if key in sql:
                raise RuntimeError(f"boom {self._leak}")
        if self._rowcounts:
            self.rowcount = self._rowcounts.pop(0)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


class NoRowcountCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = list(rows)
        self.calls: list[tuple[str, list[Any]]] = []

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        self.calls.append((sql, list(params or [])))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> Any:
        return self._cursor

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        return None


def _row(version: int, acked: str = "[]") -> tuple[Any, ...]:
    return ("t1", "owner", "2030-01-01T00:00:00+00:00", "OPEN", '["a", "b"]', acked, "", version)


def _config() -> IrisSqlConfig:
    return IrisSqlConfig(
        host="127.0.0.1", port=1972, namespace="NS", username="taskuser", password="pw"
    )


def test_default_factory_passes_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class FakeModule:
        def connect(self, **kwargs: Any) -> FakeConn:
            seen.update(kwargs)
            return FakeConn(FakeCursor())

    monkeypatch.setattr(importlib, "import_module", lambda name: FakeModule())
    conn = task_sql.default_connect(_config())
    assert isinstance(conn, FakeConn)
    assert seen == {
        "hostname": "127.0.0.1",
        "port": 1972,
        "namespace": "NS",
        "username": "taskuser",
        "password": "pw",
        "sharedmemory": False,
        "timeout": 10000,
    }


def test_driver_errors_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeModule:
        def connect(self, **kwargs: Any) -> FakeConn:
            _ = kwargs
            raise RuntimeError("credential leak hunter2 should not surface")

    monkeypatch.setattr(importlib, "import_module", lambda name: FakeModule())
    with pytest.raises(ContractError) as excinfo:
        task_sql.default_connect(_config())
    assert excinfo.value.code == "remote_error"
    assert "hunter2" not in excinfo.value.message


def _missing_import(name: str) -> Any:
    _ = name
    raise ImportError("no iris driver")


def test_missing_driver_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib, "import_module", _missing_import)
    with pytest.raises(ContractError) as excinfo:
        task_sql.default_connect(_config())
    assert excinfo.value.code == "not_configured"


def test_config_loopback_literal_and_ports() -> None:
    base = {
        "RAKATHON_IRIS_SQL_HOST": "127.0.0.1",
        "RAKATHON_IRIS_SQL_PORT": "1972",
        "RAKATHON_IRIS_SQL_NAMESPACE": "NS",
        "RAKATHON_IRIS_SQL_USER": "secret-user-xyz",
        "RAKATHON_IRIS_SQL_PASSWORD": "secret-pw-xyz",
    }
    for host in ("localhost", "db.example", "0.0.0.0"):
        with pytest.raises(ContractError):
            IrisSqlConfig.from_env(dict(base, RAKATHON_IRIS_SQL_HOST=host))
    for port in ("0", "70000", "443", "32783", "-1", "abc"):
        with pytest.raises(ContractError):
            IrisSqlConfig.from_env(dict(base, RAKATHON_IRIS_SQL_PORT=port))
    cfg = IrisSqlConfig.from_env(base)
    assert "secret-pw-xyz" not in repr(cfg) and "secret-user-xyz" not in repr(cfg)


def test_vector_sql_distinct_users() -> None:
    base = _config()
    env = {
        "RAKATHON_VECTOR_ANON_SQL_USER": "anonuser",
        "RAKATHON_VECTOR_ANON_SQL_PASSWORD": "pw2",
        "RAKATHON_VECTOR_PATIENT_SQL_USER": "patientuser",
        "RAKATHON_VECTOR_PATIENT_SQL_PASSWORD": "pw3",
    }
    anon, patient = vector_sql_configs(env, base)
    assert anon is not None and patient is not None
    assert anon.username == "anonuser" and patient.username == "patientuser"
    with pytest.raises(ContractError):
        vector_sql_configs(
            {"RAKATHON_VECTOR_ANON_SQL_USER": "taskuser", "RAKATHON_VECTOR_ANON_SQL_PASSWORD": "x"},
            base,
        )
    with pytest.raises(ContractError):
        vector_sql_configs(
            {
                "RAKATHON_VECTOR_ANON_SQL_USER": "same",
                "RAKATHON_VECTOR_ANON_SQL_PASSWORD": "x",
                "RAKATHON_VECTOR_PATIENT_SQL_USER": "same",
                "RAKATHON_VECTOR_PATIENT_SQL_PASSWORD": "y",
            },
            base,
        )
    empty_anon, empty_patient = vector_sql_configs({}, base)
    assert empty_anon is None and empty_patient is None


def test_cas_concurrent_acks_both_kept() -> None:
    first = FakeConn(FakeCursor(rows=[_row(1)], rowcounts=[0]))
    second = FakeConn(FakeCursor(rows=[_row(2, '["b"]')], rowcounts=[1]))
    conns = [first, second]

    def factory() -> FakeConn:
        return conns.pop(0)

    out = task_sql.tasks_ack(factory, "S.T", "t1", "a")
    assert sorted(out["acknowledgedBy"]) == ["a", "b"]
    assert out["version"] == 3
    assert first.rolled_back is True
    assert second.committed is True
    update_sql = second._cursor.calls[-1][0]
    assert "WHERE id = ? AND version = ?" in update_sql


def test_cas_conflict_exhausted() -> None:
    cursor = FakeCursor(rows=[_row(1)], rowcounts=[0] * 10)
    store = IrisSqlStore(_config(), tasks_factory=lambda: FakeConn(cursor))
    with pytest.raises(ContractError) as excinfo:
        store.tasks_ack("t1", "a")
    assert excinfo.value.code == "conflict"


def test_cas_idempotent_no_write() -> None:
    cursor = FakeCursor(rows=[_row(2, '["a", "b"]')])
    conn = FakeConn(cursor)
    out = task_sql.tasks_ack(lambda: conn, "S.T", "t1", "a")
    assert out["version"] == 2
    assert conn.committed is False
    assert all("UPDATE" not in sql for sql, _ in cursor.calls)


def test_rowcount_missing_fails_closed() -> None:
    cursor = NoRowcountCursor(rows=[_row(1)])
    conn = FakeConn(cursor)
    with pytest.raises(ContractError):
        task_sql.tasks_ack(lambda: conn, "S.T", "t1", "a")


def test_tasks_create_duplicate() -> None:
    task = {
        "id": "t1",
        "ownerId": "o",
        "dueAt": "2030-01-01T00:00:00+00:00",
        "status": "OPEN",
        "requiredAckUserIds": ["o"],
        "acknowledgedBy": [],
        "patientRef": None,
        "version": 1,
    }
    ok_cursor = FakeCursor()
    out = task_sql.tasks_create(lambda: FakeConn(ok_cursor), "S.T", dict(task))
    assert out["id"] == "t1"
    assert "INSERT INTO" in ok_cursor.calls[0][0]
    dupe = FakeConn(FakeCursor(rows=[("t1",)], fail_on=("INSERT",)))
    with pytest.raises(ContractError) as excinfo:
        task_sql.tasks_create(lambda: dupe, "S.T", dict(task))
    assert excinfo.value.code == "duplicate_id"


def test_anon_refuses_nonsynthetic() -> None:
    cursor = FakeCursor(rows=[("v1", "{}")])
    anon = VectorStoreConfig(
        enabled=True, schema="A", table="V", dimensions=2, synthetic_only=False
    )
    store = IrisSqlStore(
        _config(),
        tasks_factory=lambda: FakeConn(FakeCursor()),
        anon_factory=lambda: FakeConn(cursor),
        anon=anon,
    )
    with pytest.raises(ContractError):
        store.vector_search("anonymized", "[0.1, 0.2]", 5)
