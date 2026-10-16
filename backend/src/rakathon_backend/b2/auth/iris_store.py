from __future__ import annotations

import contextlib
from collections.abc import Sequence
from functools import partial
from typing import Any

from rakathon_backend.b2.auth.iris_base import IrisAuthBase, checked_rowcount, close_conn
from rakathon_backend.b2.auth.iris_rate import reserve_pair
from rakathon_backend.b2.auth.models import RateLimited, SessionRecord, StoreUnavailable

SESSION_SELECT = "token_hash, user_id, auth_version, role, created_at, last_seen, expires_at"
MAX_RATE_RETRIES = 3


def _count_with(cur: Any, conn: Any) -> int:
    return checked_rowcount(cur, conn)


def _session_from_row(row: Sequence[Any]) -> SessionRecord:
    return SessionRecord(
        token_hash=str(row[0]),
        user_id=str(row[1]),
        auth_version=int(str(row[2])),
        role=str(row[3]),
        created_at=int(str(row[4])),
        last_seen=int(str(row[5])),
        expires_at=int(str(row[6])),
    )


class IrisAuthStore(IrisAuthBase):
    def create_session(self, record: SessionRecord) -> None:
        _, sessions, _ = self._tables()
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"INSERT INTO {sessions} (token_hash, user_id, auth_version, role,"
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
                conn.commit()
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.rollback()
                raise StoreUnavailable() from exc
        finally:
            close_conn(conn)

    def get_session(self, token_hash: str) -> SessionRecord | None:
        _, sessions, _ = self._tables()
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"SELECT TOP 1 {SESSION_SELECT} FROM {sessions} WHERE token_hash = ?",
                    [token_hash],
                )
                rows = cur.fetchall()
            except Exception as exc:
                raise StoreUnavailable() from exc
        finally:
            close_conn(conn)
        if not rows:
            return None
        return _session_from_row(list(rows[0]))

    def cas_last_seen(self, token_hash: str, old: int, new: int) -> bool:
        _, sessions, _ = self._tables()
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE {sessions} SET last_seen = ? WHERE token_hash = ?"
                    " AND last_seen = ? AND expires_at > ?",
                    [new, token_hash, old, new],
                )
                matched = checked_rowcount(cur, conn)
                if matched == 1:
                    conn.commit()
                    return True
                with contextlib.suppress(Exception):
                    conn.rollback()
                return False
            except StoreUnavailable:
                raise
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.rollback()
                raise StoreUnavailable() from exc
        finally:
            close_conn(conn)

    def delete_session(self, token_hash: str) -> None:
        _, sessions, _ = self._tables()
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(f"DELETE FROM {sessions} WHERE token_hash = ?", [token_hash])
                conn.commit()
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.rollback()
                raise StoreUnavailable() from exc
        finally:
            close_conn(conn)

    def count_user_sessions(self, user_id: str) -> int:
        _, sessions, _ = self._tables()
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(f"SELECT COUNT(*) FROM {sessions} WHERE user_id = ?", [user_id])
                rows = cur.fetchall()
            except Exception as exc:
                raise StoreUnavailable() from exc
        finally:
            close_conn(conn)
        if not rows:
            return 0
        return int(str(next(iter(rows[0]))))

    def prune_user_sessions(self, user_id: str, keep: int) -> None:
        _, sessions, _ = self._tables()
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"SELECT TOP {int(keep) + 1000} token_hash, last_seen FROM {sessions}"
                    " WHERE user_id = ? ORDER BY last_seen ASC",
                    [user_id],
                )
                rows = [(str(r[0]), int(str(r[1]))) for r in cur.fetchall()]
                excess = rows[: max(0, len(rows) - int(keep))]
                for token, seen in excess:
                    cur.execute(
                        f"DELETE FROM {sessions} WHERE token_hash = ?"
                        " AND user_id = ? AND last_seen = ?",
                        [token, user_id, seen],
                    )
                conn.commit()
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.rollback()
                raise StoreUnavailable() from exc
        finally:
            close_conn(conn)

    def revoke_user_sessions(self, user_id: str) -> None:
        _, sessions, _ = self._tables()
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(f"DELETE FROM {sessions} WHERE user_id = ?", [user_id])
                conn.commit()
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.rollback()
                raise StoreUnavailable() from exc
        finally:
            close_conn(conn)

    def prune_expired_sessions(self, now: int, limit: int) -> None:
        _, sessions, _ = self._tables()
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"SELECT TOP {int(limit)} token_hash FROM {sessions} WHERE expires_at <= ?",
                    [now],
                )
                rows = [str(next(iter(r))) for r in cur.fetchall()]
                for token in rows:
                    cur.execute(
                        f"DELETE FROM {sessions} WHERE token_hash = ? AND expires_at <= ?",
                        [token, now],
                    )
                conn.commit()
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.rollback()
                raise StoreUnavailable() from exc
        finally:
            close_conn(conn)

    def rate_reserve(
        self,
        account_key: str,
        now: int,
        account_limit: int,
        account_window: int,
        global_limit: int,
        global_window: int,
    ) -> None:
        _, _, rate = self._tables()
        errors = 0
        for _ in range(MAX_RATE_RETRIES + 1):
            try:
                conn = self._conn()
            except StoreUnavailable:
                errors += 1
                if errors > MAX_RATE_RETRIES:
                    raise
                continue
            try:
                cur = conn.cursor()
                try:
                    reserve_pair(
                        cur,
                        partial(_count_with, conn=conn),
                        conn.commit,
                        conn.rollback,
                        rate,
                        account_key,
                        now,
                        account_limit,
                        account_window,
                        global_limit,
                        global_window,
                    )
                    return
                except RateLimited:
                    raise
                except StoreUnavailable:
                    raise
                except Exception as exc:
                    with contextlib.suppress(Exception):
                        conn.rollback()
                    raise StoreUnavailable() from exc
            except StoreUnavailable:
                errors += 1
                if errors > MAX_RATE_RETRIES:
                    raise
            except RateLimited:
                raise
            finally:
                close_conn(conn)
