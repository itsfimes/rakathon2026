from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.b2.auth.iris_store import IrisAuthStore
from rakathon_backend.b2.auth.models import RateLimited, SessionRecord, StoreUnavailable
from rakathon_backend.b2.iris.config import IrisSqlConfig

TOP_RE = re.compile(r"^SELECT TOP (\d+) ", re.IGNORECASE)


def translate(sql: str) -> str:
    out = sql.replace("FSB.", "")
    match = TOP_RE.match(out)
    if match:
        out = "SELECT " + out[match.end() :]
        out = out + f" LIMIT {int(match.group(1))}"
    return out


class FakeCursor:
    def __init__(self, raw: sqlite3.Connection, log: list[tuple[str, list[Any]]]) -> None:
        self._cur = raw.cursor()
        self._log = log
        self.rowcount: int = 0
        self._rows: list[Any] = []

    def execute(self, sql: str, params: Any = None) -> Any:
        bound = list(params) if params else []
        assert "?" in sql or bound == []
        assert isinstance(params, (list, tuple)) or params is None
        self._log.append((sql, bound))
        cur = self._cur.execute(translate(sql), bound)
        if cur.description is not None:
            self._rows = [tuple(row) for row in cur.fetchall()]
            self.rowcount = len(self._rows)
        else:
            self._rows = []
            self.rowcount = cur.rowcount if isinstance(cur.rowcount, int) else 0
        return self

    def fetchall(self) -> list[Any]:
        return list(self._rows)

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self, path: str, log: list[tuple[str, list[Any]]]) -> None:
        self._raw = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
        self._log = log

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._raw, self._log)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()


def make_store(tmp_path: Path) -> tuple[IrisAuthStore, list[tuple[str, list[Any]]]]:
    db = str(tmp_path / "iris_fake.db")
    log: list[tuple[str, list[Any]]] = []
    config = IrisSqlConfig(
        host="127.0.0.1", port=1972, namespace="USER", username="u", password="p", schema="FSB"
    )
    store = IrisAuthStore(config, factory=lambda: FakeConnection(db, log))
    store.init_schema()
    return (store, log)


def make_session(user: str, token: str, seen: int) -> SessionRecord:
    return SessionRecord(
        token_hash=token,
        user_id=user,
        auth_version=1,
        role="viewer",
        created_at=seen,
        last_seen=seen,
        expires_at=seen + 100000,
    )


def count_rate(tmp_path: Path, scope: str) -> int:
    conn = sqlite3.connect(str(tmp_path / "iris_fake.db"))
    try:
        row = conn.execute("SELECT COUNT(*) FROM AuthRate WHERE scope = ?", [scope]).fetchone()
    finally:
        conn.close()
    return int(str(row[0]))


def test_rate_cap_enforced_under_barrier(tmp_path: Path) -> None:
    store, log = make_store(tmp_path)
    barrier = threading.Barrier(8)
    allowed: list[bool] = []
    denied: list[bool] = []

    def attempt() -> None:
        barrier.wait(timeout=30.0)
        try:
            store.rate_reserve("shared-acct", 5000, 5, 60, 1000, 60)
            allowed.append(True)
        except RateLimited:
            denied.append(True)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(allowed) + len(denied) == 8
    assert count_rate(tmp_path, "acct") <= 5
    assert count_rate(tmp_path, "acct") == len(allowed)
    for sql, params in log:
        assert "?" in sql or params == []


def test_global_limit_rolls_back_partial(tmp_path: Path) -> None:
    store, _ = make_store(tmp_path)
    store.rate_reserve("solo", 6000, 100, 60, 1, 60)
    with pytest.raises(RateLimited):
        store.rate_reserve("solo", 6000, 100, 60, 1, 60)
    assert count_rate(tmp_path, "acct") == 1
    assert count_rate(tmp_path, "glob") == 1


def test_prune_skips_refreshed_session(tmp_path: Path) -> None:
    store, _ = make_store(tmp_path)
    user = "u" * 32
    tokens = [f"t{i:062d}" for i in range(5)]
    for pos, token in enumerate(tokens):
        store.create_session(make_session(user, token, 1000 + pos))
    assert store.count_user_sessions(user) == 5
    refreshed: list[bool] = []

    original_factory = store._factory

    def refreshing_factory() -> Any:
        conn = original_factory()
        inner = conn.cursor()

        class RefreshCursor:
            def __init__(self, wrapped: Any) -> None:
                self._wrapped = wrapped
                self.rowcount = 0

            def execute(self, sql: str, params: Any = None) -> Any:
                self._wrapped.execute(sql, params)
                self.rowcount = self._wrapped.rowcount
                if sql.startswith("SELECT TOP") and "last_seen" in sql and not refreshed:
                    refreshed.append(True)
                    inner.execute(
                        "UPDATE AuthSessions SET last_seen = ? WHERE token_hash = ?",
                        [9999, tokens[0]],
                    )
                return self

            def fetchall(self) -> list[Any]:
                rows: list[Any] = self._wrapped.fetchall()
                return list(rows)

        class RefreshConn:
            def cursor(self) -> Any:
                return RefreshCursor(conn.cursor())

            def commit(self) -> None:
                return conn.commit()

            def rollback(self) -> None:
                return conn.rollback()

            def close(self) -> None:
                return conn.close()

        return RefreshConn()

    store._factory = refreshing_factory
    try:
        store.prune_user_sessions(user, 3)
    finally:
        store._factory = original_factory
    assert refreshed == [True]
    remaining = store.count_user_sessions(user)
    assert remaining >= 3
    assert store.get_session(tokens[0]) is not None
    kept = store.get_session(tokens[0])
    assert kept is not None
    assert kept.last_seen == 9999


def test_expired_prune_bounded_growth(tmp_path: Path) -> None:
    store, _ = make_store(tmp_path)
    user = "v" * 32
    for pos in range(40):
        token = f"e{pos:062d}"
        rec = SessionRecord(
            token_hash=token,
            user_id=user,
            auth_version=1,
            role="viewer",
            created_at=100,
            last_seen=100,
            expires_at=200,
        )
        store.create_session(rec)
    assert store.count_user_sessions(user) == 40
    store.prune_expired_sessions(500, 15)
    assert store.count_user_sessions(user) == 25
    store.prune_expired_sessions(500, 100)
    assert store.count_user_sessions(user) == 0


def test_transient_error_retries_then_surfaces(tmp_path: Path) -> None:
    store, _ = make_store(tmp_path)
    calls = [0]

    def flaky() -> Any:
        calls[0] += 1
        if calls[0] == 1:
            raise StoreUnavailable()
        db = str(tmp_path / "iris_fake.db")
        return FakeConnection(db, [])

    store._factory = flaky
    store.rate_reserve("retry-acct", 7000, 10, 60, 100, 60)
    assert calls[0] >= 2
    assert count_rate(tmp_path, "acct") == 1


def test_slot_schema_has_unique_guard(tmp_path: Path) -> None:
    make_store(tmp_path)
    conn = sqlite3.connect(str(tmp_path / "iris_fake.db"))
    try:
        ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", ["AuthRate"]).fetchone()[
            0
        ]
        indexes = [row[0] for row in conn.execute("PRAGMA index_list(AuthRate)").fetchall()]
        unique_defs = [conn.execute(f"PRAGMA index_info({name})").fetchall() for name in indexes]
    finally:
        conn.close()
    assert "PRIMARY KEY" in str(ddl).upper() or "UNIQUE" in str(ddl).upper()
    assert "scope" in str(ddl) and "slot" in str(ddl)
    assert unique_defs != []


def test_many_instances_shared_db_enforces_cap(tmp_path: Path) -> None:
    db = str(tmp_path / "iris_fake.db")
    config = IrisSqlConfig(
        host="127.0.0.1", port=1972, namespace="USER", username="u", password="p", schema="FSB"
    )
    first = IrisAuthStore(config, factory=lambda: FakeConnection(db, []))
    first.init_schema()
    barrier = threading.Barrier(10)
    allowed: list[bool] = []
    denied: list[bool] = []

    def attempt() -> None:
        local = IrisAuthStore(config, factory=lambda: FakeConnection(db, []))
        barrier.wait(timeout=30.0)
        try:
            local.rate_reserve("shared-many", 8000, 5, 60, 1000, 60)
            allowed.append(True)
        except RateLimited:
            denied.append(True)

    threads = [threading.Thread(target=attempt) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(allowed) + len(denied) == 10
    assert len(allowed) == 5
    assert count_rate(tmp_path, "acct") == 5


def test_stale_slot_reused_after_window(tmp_path: Path) -> None:
    store, _ = make_store(tmp_path)
    store.rate_reserve("stale-acct", 9000, 2, 60, 1000, 60)
    store.rate_reserve("stale-acct", 9000, 2, 60, 1000, 60)
    with pytest.raises(RateLimited):
        store.rate_reserve("stale-acct", 9000, 2, 60, 1000, 60)
    store.rate_reserve("stale-acct", 9000 + 61, 2, 60, 1000, 60)
    conn = sqlite3.connect(str(tmp_path / "iris_fake.db"))
    try:
        rows = conn.execute(
            "SELECT COUNT(*) FROM AuthRate WHERE scope = ? AND key = ?", ["acct", "stale-acct"]
        ).fetchone()
    finally:
        conn.close()
    assert int(str(rows[0])) == 2


def test_global_rollback_releases_only_own_slot(tmp_path: Path) -> None:
    store, _ = make_store(tmp_path)
    store.rate_reserve("solo", 9500, 100, 60, 1, 60)
    with pytest.raises(RateLimited):
        store.rate_reserve("other", 9500, 100, 60, 1, 60)
    conn = sqlite3.connect(str(tmp_path / "iris_fake.db"))
    try:
        solo = conn.execute(
            "SELECT COUNT(*) FROM AuthRate WHERE scope = ? AND key = ?", ["acct", "solo"]
        ).fetchone()
        other = conn.execute(
            "SELECT COUNT(*) FROM AuthRate WHERE scope = ? AND key = ?", ["acct", "other"]
        ).fetchone()
        glob = conn.execute("SELECT COUNT(*) FROM AuthRate WHERE scope = ?", ["glob"]).fetchone()
    finally:
        conn.close()
    assert int(str(solo[0])) == 1
    assert int(str(other[0])) == 0
    assert int(str(glob[0])) == 1
