from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.b2.auth.iris_base import IrisAuthBase
from rakathon_backend.b2.auth.iris_store import IrisAuthStore
from rakathon_backend.b2.auth.keys import generate_key_file, load_key_file
from rakathon_backend.b2.auth.models import SessionRecord, StoreUnavailable, UserRecord
from rakathon_backend.b2.iris.config import IrisSqlConfig
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.common.errors import ContractError

PW_HASH = (
    "$argon2id$v=19$m=19456,t=2,p=1$"
    + "c2FsdHNhbHRzYWx0czE"
    + "$"
    + "aGFzaGhhc2hoYXNoaGFzaGhhc2hoYXNoaGFzaA"
)


class FakeCursor:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn
        self.rowcount: int = 0
        self._rows: list[Any] = []

    def execute(self, sql: str, params: Any = None) -> Any:
        assert "?" in sql or params == []
        assert params is None or isinstance(params, (list, tuple))
        self._conn.statements.append((sql, list(params) if params else []))
        if self._conn.fail_next:
            self._conn.fail_next = False
            raise RuntimeError("boom")
        if sql.startswith("SELECT COUNT"):
            self._rows = [(0,)]
            self.rowcount = 0
        elif sql.startswith(("SELECT TOP 1 token_hash", "SELECT TOP")):
            self._rows = []
            self.rowcount = 0
        elif sql.startswith(("UPDATE", "INSERT INTO")):
            self.rowcount = 1
        else:
            self.rowcount = 0
            self._rows = []
        return self

    def fetchall(self) -> list[Any]:
        return list(self._rows)

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, list[Any]]] = []
        self.committed = 0
        self.rolled_back = 0
        self.closed = 0
        self.fail_next = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def close(self) -> None:
        self.closed += 1


def make_config() -> IrisSqlConfig:
    return IrisSqlConfig(
        host="127.0.0.1", port=1972, namespace="USER", username="u", password="p", schema="FSB"
    )


def test_iris_params_bound_and_commit() -> None:
    conn = FakeConnection()
    store = IrisAuthStore(make_config(), factory=lambda: conn)
    rec = UserRecord(
        user_id="a" * 32,
        username_index="b" * 64,
        password_hash=PW_HASH,
        enc_nonce=b"n" * 12,
        enc_ct=b"c" * 32,
        key_id="k1",
        role="viewer",
        active=True,
        auth_version=1,
        created_at=100,
        updated_at=100,
    )
    store.create_user(rec)
    assert conn.committed == 1
    for sql, params in conn.statements:
        assert "?" in sql
        assert len(params) >= 1


def test_iris_rollback_on_error() -> None:
    conn = FakeConnection()
    conn.fail_next = True
    store = IrisAuthStore(make_config(), factory=lambda: conn)
    with pytest.raises(StoreUnavailable):
        store.init_schema()
    assert conn.rolled_back >= 1
    assert conn.closed >= 1


def test_iris_bad_identifier_rejected() -> None:
    bad = IrisSqlConfig(
        host="127.0.0.1",
        port=1972,
        namespace="USER",
        username="u",
        password="p",
        schema="bad-schema!",
    )
    store = IrisAuthStore(bad, factory=lambda: FakeConnection())
    with pytest.raises(ContractError):
        store.init_schema()


def test_iris_missing_driver_fail_closed() -> None:
    def no_driver() -> Any:
        raise ContractError(code="not_configured", message="iris driver is not installed")

    store = IrisAuthStore(make_config(), factory=no_driver)
    with pytest.raises(StoreUnavailable):
        store.init_schema()
    with pytest.raises(StoreUnavailable):
        store.get_user_by_id("a" * 32)


def test_iris_no_fallback_session_missing() -> None:
    conn = FakeConnection()
    store = IrisAuthStore(make_config(), factory=lambda: conn)
    assert store.get_session("f" * 64) is None
    assert conn.closed == 1


def test_keyfile_permissions_and_symlink(tmp_path: Path) -> None:
    target = tmp_path / "auth.key"
    generate_key_file(target)
    os.chmod(str(target), 0o644)
    with pytest.raises(ContractError):
        load_key_file(target)
    os.chmod(str(target), 0o600)
    link = tmp_path / "link.key"
    link.symlink_to(target)
    with pytest.raises(ContractError):
        load_key_file(link)


def test_keyfile_parent_must_be_private(tmp_path: Path) -> None:
    target = tmp_path / "auth.key"
    os.chmod(str(tmp_path), 0o755)
    try:
        with pytest.raises(ContractError):
            generate_key_file(target)
    finally:
        os.chmod(str(tmp_path), 0o700)


def test_hash_unique_no_reversal() -> None:
    provider = LocalPasswordProvider(time_cost=2, memory_cost=19456, parallelism=1)
    first = provider.hash_password("correct-horse-battery-staple-x")
    second = provider.hash_password("correct-horse-battery-staple-x")
    assert first != second
    assert "correct-horse" not in first
    assert provider.verify(first, "correct-horse-battery-staple-x") is True
    assert provider.verify(first, "wrong-wrong-wrong-password") is False


def test_iris_base_tables_qualified() -> None:
    base = IrisAuthBase(make_config(), factory=lambda: FakeConnection())
    users, sessions, rate = base._tables()
    assert users == "FSB.AuthUsers"
    assert sessions == "FSB.AuthSessions"
    assert rate == "FSB.AuthRate"
    assert stat.S_IMODE(0o600) == 0o600
    _ = SessionRecord(
        token_hash="t",
        user_id="u",
        auth_version=1,
        role="viewer",
        created_at=1,
        last_seen=1,
        expires_at=2,
    )
