from __future__ import annotations

import base64
import contextlib
from collections.abc import Sequence
from typing import Any

from rakathon_backend.b2.auth.models import StoreUnavailable, UserRecord
from rakathon_backend.b2.iris import task_sql
from rakathon_backend.b2.iris.config import IrisSqlConfig
from rakathon_backend.b2.iris.task_sql import Factory
from rakathon_backend.common.errors import ContractError

USERS_TABLE = "AuthUsers"
SESSIONS_TABLE = "AuthSessions"
RATE_TABLE = "AuthRate"
USER_SELECT = (
    "user_id, username_index, password_hash, enc_nonce, enc_ct,"
    " key_id, role, active, auth_version, created_at, updated_at"
)


def qualified(schema: str, table: str) -> str:
    return task_sql.qualified_table(schema, table)


def close_conn(conn: Any) -> None:
    with contextlib.suppress(Exception):
        conn.close()


def checked_rowcount(cur: Any, conn: Any) -> int:
    raw = getattr(cur, "rowcount", None)
    if type(raw) is bool or not isinstance(raw, int):
        with contextlib.suppress(Exception):
            conn.rollback()
        raise StoreUnavailable()
    return raw


def user_from_row(row: Sequence[Any]) -> UserRecord:
    return UserRecord(
        user_id=str(row[0]),
        username_index=str(row[1]),
        password_hash=str(row[2]),
        enc_nonce=base64.b64decode(str(row[3])),
        enc_ct=base64.b64decode(str(row[4])),
        key_id=str(row[5]),
        role=str(row[6]),
        active=str(row[7]) == "1",
        auth_version=int(str(row[8])),
        created_at=int(str(row[9])),
        updated_at=int(str(row[10])),
    )


class IrisAuthBase:
    def __init__(self, config: IrisSqlConfig, factory: Factory | None = None) -> None:
        self._config = config
        self._factory: Factory = factory if factory is not None else task_sql.make_factory(config)

    def _conn(self) -> Any:
        try:
            return self._factory()
        except ContractError as exc:
            raise StoreUnavailable() from exc
        except Exception as exc:
            raise StoreUnavailable() from exc

    def _tables(self) -> tuple[str, str, str]:
        schema = self._config.schema
        return (
            qualified(schema, USERS_TABLE),
            qualified(schema, SESSIONS_TABLE),
            qualified(schema, RATE_TABLE),
        )

    def init_schema(self) -> None:
        users, sessions, rate = self._tables()
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"CREATE TABLE {users} (user_id VARCHAR(64) PRIMARY KEY,"
                    " username_index VARCHAR(128) UNIQUE, password_hash VARCHAR(512),"
                    " enc_nonce VARCHAR(64), enc_ct VARCHAR(1024), key_id VARCHAR(64),"
                    " role VARCHAR(32), active VARCHAR(4), auth_version INT,"
                    " created_at BIGINT, updated_at BIGINT)",
                    [],
                )
                cur.execute(
                    f"CREATE TABLE {sessions} (token_hash VARCHAR(128) PRIMARY KEY,"
                    " user_id VARCHAR(64), auth_version INT, role VARCHAR(32),"
                    " created_at BIGINT, last_seen BIGINT, expires_at BIGINT)",
                    [],
                )
                cur.execute(
                    f"CREATE TABLE {rate} (scope VARCHAR(16), key VARCHAR(256),"
                    " slot INT, ts BIGINT, reservation_id VARCHAR(64),"
                    " PRIMARY KEY (scope, key, slot))",
                    [],
                )
                conn.commit()
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.rollback()
                raise StoreUnavailable() from exc
        finally:
            close_conn(conn)

    def create_user(self, record: UserRecord) -> None:
        users, _, _ = self._tables()
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"INSERT INTO {users} (user_id, username_index, password_hash,"
                    " enc_nonce, enc_ct, key_id, role, active, auth_version,"
                    " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        record.user_id,
                        record.username_index,
                        record.password_hash,
                        base64.b64encode(bytes(record.enc_nonce)).decode("ascii"),
                        base64.b64encode(bytes(record.enc_ct)).decode("ascii"),
                        record.key_id,
                        record.role,
                        "1" if record.active else "0",
                        record.auth_version,
                        record.created_at,
                        record.updated_at,
                    ],
                )
                conn.commit()
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.rollback()
                if self.get_user_by_index(record.username_index) is not None:
                    raise ContractError(code="duplicate_id", message="user exists") from exc
                raise StoreUnavailable() from exc
        finally:
            close_conn(conn)

    def get_user_by_index(self, username_index: str) -> UserRecord | None:
        users, _, _ = self._tables()
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"SELECT TOP 1 {USER_SELECT} FROM {users} WHERE username_index = ?",
                    [username_index],
                )
                rows = cur.fetchall()
            except Exception as exc:
                raise StoreUnavailable() from exc
        finally:
            close_conn(conn)
        if not rows:
            return None
        return user_from_row(list(rows[0]))

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        users, _, _ = self._tables()
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"SELECT TOP 1 {USER_SELECT} FROM {users} WHERE user_id = ?",
                    [user_id],
                )
                rows = cur.fetchall()
            except Exception as exc:
                raise StoreUnavailable() from exc
        finally:
            close_conn(conn)
        if not rows:
            return None
        return user_from_row(list(rows[0]))

    def update_user(self, record: UserRecord) -> None:
        users, _, _ = self._tables()
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE {users} SET username_index = ?, password_hash = ?,"
                    " enc_nonce = ?, enc_ct = ?, key_id = ?, role = ?, active = ?,"
                    " auth_version = ?, updated_at = ? WHERE user_id = ?",
                    [
                        record.username_index,
                        record.password_hash,
                        base64.b64encode(bytes(record.enc_nonce)).decode("ascii"),
                        base64.b64encode(bytes(record.enc_ct)).decode("ascii"),
                        record.key_id,
                        record.role,
                        "1" if record.active else "0",
                        record.auth_version,
                        record.updated_at,
                        record.user_id,
                    ],
                )
                matched = checked_rowcount(cur, conn)
                if matched != 1:
                    with contextlib.suppress(Exception):
                        conn.rollback()
                    raise StoreUnavailable()
                conn.commit()
            except (StoreUnavailable, ContractError):
                raise
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.rollback()
                raise StoreUnavailable() from exc
        finally:
            close_conn(conn)
