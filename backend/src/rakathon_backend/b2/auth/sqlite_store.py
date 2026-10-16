from __future__ import annotations

import sqlite3

from rakathon_backend.b2.auth.iris_rate import reserve_pair
from rakathon_backend.b2.auth.models import RateLimited, SessionRecord, StoreUnavailable
from rakathon_backend.b2.auth.sqlite_base import SQLiteAuthBase, row_to_session


class _SlotCursor:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._rows: list[tuple[object, ...]] = []
        self.rowcount: int = 0

    def execute(self, sql: str, params: list[object] | None = None) -> _SlotCursor:
        cur = self._conn.execute(sql, params or [])
        if cur.description is not None:
            self._rows = [tuple(row) for row in cur.fetchall()]
            self.rowcount = len(self._rows)
        else:
            self._rows = []
            raw = cur.rowcount
            self.rowcount = raw if isinstance(raw, int) and type(raw) is not bool else 0
        return self

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._rows)


class SQLiteDemoAuthStore(SQLiteAuthBase):
    def create_session(self, record: SessionRecord) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE", [])
            conn.execute(
                "INSERT INTO auth_sessions (token_hash, user_id, auth_version, role,"
                " created_at, last_seen, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    record.token_hash,
                    record.user_id,
                    record.auth_version,
                    record.role,
                    record.created_at,
                    record.last_seen,
                    record.expires_at,
                ],
            )
            conn.execute("COMMIT", [])
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK", [])
            except sqlite3.Error:
                pass
            conn.close()
            raise StoreUnavailable() from exc
        conn.close()

    def get_session(self, token_hash: str) -> SessionRecord | None:
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT token_hash, user_id, auth_version, role, created_at, last_seen,"
                " expires_at FROM auth_sessions WHERE token_hash = ?",
                [token_hash],
            )
            row = cur.fetchone()
        except sqlite3.Error as exc:
            conn.close()
            raise StoreUnavailable() from exc
        conn.close()
        return row_to_session(tuple(row)) if row is not None else None

    def cas_last_seen(self, token_hash: str, old: int, new: int) -> bool:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE", [])
            cur = conn.execute(
                "UPDATE auth_sessions SET last_seen = ? WHERE token_hash = ?"
                " AND last_seen = ? AND expires_at > ?",
                [new, token_hash, old, new],
            )
            ok = cur.rowcount == 1
            conn.execute("COMMIT" if ok else "ROLLBACK", [])
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK", [])
            except sqlite3.Error:
                pass
            conn.close()
            raise StoreUnavailable() from exc
        conn.close()
        return ok

    def delete_session(self, token_hash: str) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE", [])
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", [token_hash])
            conn.execute("COMMIT", [])
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK", [])
            except sqlite3.Error:
                pass
            conn.close()
            raise StoreUnavailable() from exc
        conn.close()

    def count_user_sessions(self, user_id: str) -> int:
        conn = self._connect()
        try:
            cur = conn.execute("SELECT COUNT(*) FROM auth_sessions WHERE user_id = ?", [user_id])
            row = cur.fetchone()
        except sqlite3.Error as exc:
            conn.close()
            raise StoreUnavailable() from exc
        conn.close()
        return int(str(row[0])) if row else 0

    def prune_user_sessions(self, user_id: str, keep: int) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE", [])
            conn.execute(
                "DELETE FROM auth_sessions WHERE token_hash IN (SELECT token_hash"
                " FROM auth_sessions WHERE user_id = ? ORDER BY last_seen ASC"
                " LIMIT -1 OFFSET ?)",
                [user_id, keep],
            )
            conn.execute("COMMIT", [])
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK", [])
            except sqlite3.Error:
                pass
            conn.close()
            raise StoreUnavailable() from exc
        conn.close()

    def revoke_user_sessions(self, user_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE", [])
            conn.execute("DELETE FROM auth_sessions WHERE user_id = ?", [user_id])
            conn.execute("COMMIT", [])
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK", [])
            except sqlite3.Error:
                pass
            conn.close()
            raise StoreUnavailable() from exc
        conn.close()

    def prune_expired_sessions(self, now: int, limit: int) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE", [])
            conn.execute(
                "DELETE FROM auth_sessions WHERE token_hash IN (SELECT token_hash"
                " FROM auth_sessions WHERE expires_at <= ? LIMIT ?)",
                [now, limit],
            )
            conn.execute("COMMIT", [])
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK", [])
            except sqlite3.Error:
                pass
            conn.close()
            raise StoreUnavailable() from exc
        conn.close()

    def rate_reserve(
        self,
        account_key: str,
        now: int,
        account_limit: int,
        account_window: int,
        global_limit: int,
        global_window: int,
    ) -> None:
        last: Exception | None = None
        for _ in range(4):
            conn = self._connect()
            try:
                cur = _SlotCursor(conn)
                reserve_pair(
                    cur,
                    lambda c: int(c.rowcount),
                    conn.commit,
                    conn.rollback,
                    "auth_rate",
                    account_key,
                    now,
                    account_limit,
                    account_window,
                    global_limit,
                    global_window,
                )
                conn.close()
                return
            except RateLimited:
                conn.close()
                raise
            except StoreUnavailable as exc:
                last = exc
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                conn.close()
                continue
            except sqlite3.Error as exc:
                last = StoreUnavailable()
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                conn.close()
                _ = exc
                continue
        if isinstance(last, StoreUnavailable):
            raise last
        raise StoreUnavailable()
