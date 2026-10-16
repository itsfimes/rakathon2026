from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path
from typing import Any

from rakathon_backend.b2.auth.models import SessionRecord, StoreUnavailable, UserRecord
from rakathon_backend.common.errors import ContractError

DDL_USERS = (
    "CREATE TABLE IF NOT EXISTS auth_users (user_id TEXT PRIMARY KEY, "
    "username_index TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, "
    "enc_nonce BLOB NOT NULL, enc_ct BLOB NOT NULL, key_id TEXT NOT NULL, "
    "role TEXT NOT NULL, active INTEGER NOT NULL, auth_version INTEGER NOT NULL, "
    "created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)"
)
DDL_SESSIONS = (
    "CREATE TABLE IF NOT EXISTS auth_sessions (token_hash TEXT PRIMARY KEY, "
    "user_id TEXT NOT NULL, auth_version INTEGER NOT NULL, role TEXT NOT NULL, "
    "created_at INTEGER NOT NULL, last_seen INTEGER NOT NULL, expires_at INTEGER NOT NULL)"
)
DDL_SESSION_IDX = "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions (user_id)"
DDL_RATE = "CREATE TABLE IF NOT EXISTS auth_rate (scope TEXT NOT NULL, key TEXT NOT NULL, slot INTEGER NOT NULL, ts INTEGER NOT NULL, reservation_id TEXT NOT NULL, PRIMARY KEY (scope, key, slot))"
DDL_RATE_IDX = "CREATE INDEX IF NOT EXISTS idx_auth_rate_scope ON auth_rate (scope, key, ts)"
USER_COLS = "user_id, username_index, password_hash, enc_nonce, enc_ct, key_id, role, active, auth_version, created_at, updated_at"


def check_parent(path: Path) -> None:
    try:
        st = path.parent.lstat()
    except OSError as exc:
        raise StoreUnavailable() from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise StoreUnavailable()
    try:
        if st.st_uid != os.geteuid():
            raise StoreUnavailable()
    except AttributeError:
        pass
    if (st.st_mode & 0o077) != 0:
        raise StoreUnavailable()


def check_existing(path: Path) -> None:
    try:
        st = path.lstat()
    except OSError as exc:
        raise StoreUnavailable() from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise StoreUnavailable()
    try:
        if st.st_uid != os.geteuid():
            raise StoreUnavailable()
    except AttributeError:
        pass
    if (st.st_mode & 0o777) != 0o600:
        raise StoreUnavailable()
    for suffix in ("-wal", "-journal", "-shm"):
        side = Path(str(path) + suffix)
        try:
            sst = side.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise StoreUnavailable() from exc
        if stat.S_ISLNK(sst.st_mode) or not stat.S_ISREG(sst.st_mode):
            raise StoreUnavailable()
        try:
            if sst.st_uid != os.geteuid():
                raise StoreUnavailable()
        except AttributeError:
            pass
        if (sst.st_mode & 0o777) != 0o600:
            raise StoreUnavailable()


def row_to_user(row: tuple[Any, ...]) -> UserRecord:
    return UserRecord(
        user_id=str(row[0]),
        username_index=str(row[1]),
        password_hash=str(row[2]),
        enc_nonce=bytes(row[3]),
        enc_ct=bytes(row[4]),
        key_id=str(row[5]),
        role=str(row[6]),
        active=bool(int(str(row[7]))),
        auth_version=int(str(row[8])),
        created_at=int(str(row[9])),
        updated_at=int(str(row[10])),
    )


def row_to_session(row: tuple[object, ...]) -> SessionRecord:
    return SessionRecord(
        token_hash=str(row[0]),
        user_id=str(row[1]),
        auth_version=int(str(row[2])),
        role=str(row[3]),
        created_at=int(str(row[4])),
        last_seen=int(str(row[5])),
        expires_at=int(str(row[6])),
    )


class SQLiteAuthBase:
    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect(self) -> sqlite3.Connection:
        check_parent(self._path)
        if self._path.exists():
            check_existing(self._path)
        else:
            raise StoreUnavailable()
        try:
            conn = sqlite3.connect(str(self._path), timeout=10, isolation_level=None)
        except sqlite3.Error as exc:
            raise StoreUnavailable() from exc
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA synchronous=FULL")
        except sqlite3.Error:
            conn.close()
            raise StoreUnavailable()
        return conn

    def init_schema(self) -> None:
        check_parent(self._path)
        if self._path.exists():
            check_existing(self._path)
        else:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(str(self._path), flags, 0o600)
                os.close(fd)
            except OSError as exc:
                raise StoreUnavailable() from exc
            try:
                os.chmod(str(self._path), 0o600)
            except OSError:
                pass
        try:
            conn = sqlite3.connect(str(self._path), timeout=10, isolation_level=None)
        except sqlite3.Error as exc:
            raise StoreUnavailable() from exc
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(DDL_USERS, [])
            conn.execute(DDL_SESSIONS, [])
            conn.execute(DDL_SESSION_IDX, [])
            conn.execute(DDL_RATE, [])
            conn.execute(DDL_RATE_IDX, [])
            conn.execute("COMMIT", [])
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK", [])
            except sqlite3.Error:
                pass
            conn.close()
            raise StoreUnavailable() from exc
        conn.close()

    def create_user(self, record: UserRecord) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE", [])
            conn.execute(
                "INSERT INTO auth_users (user_id, username_index, password_hash, enc_nonce,"
                " enc_ct, key_id, role, active, auth_version, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    record.user_id,
                    record.username_index,
                    record.password_hash,
                    bytes(record.enc_nonce),
                    bytes(record.enc_ct),
                    record.key_id,
                    record.role,
                    1 if record.active else 0,
                    record.auth_version,
                    record.created_at,
                    record.updated_at,
                ],
            )
            conn.execute("COMMIT", [])
        except sqlite3.IntegrityError as exc:
            try:
                conn.execute("ROLLBACK", [])
            except sqlite3.Error:
                pass
            conn.close()
            raise ContractError(code="duplicate_id", message="user exists") from exc
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK", [])
            except sqlite3.Error:
                pass
            conn.close()
            raise StoreUnavailable() from exc
        conn.close()

    def get_user_by_index(self, username_index: str) -> UserRecord | None:
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT " + USER_COLS + " FROM auth_users WHERE username_index = ?",
                [username_index],
            )
            row = cur.fetchone()
        except sqlite3.Error as exc:
            conn.close()
            raise StoreUnavailable() from exc
        conn.close()
        return row_to_user(tuple(row)) if row is not None else None

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT " + USER_COLS + " FROM auth_users WHERE user_id = ?",
                [user_id],
            )
            row = cur.fetchone()
        except sqlite3.Error as exc:
            conn.close()
            raise StoreUnavailable() from exc
        conn.close()
        return row_to_user(tuple(row)) if row is not None else None

    def update_user(self, record: UserRecord) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE", [])
            cur = conn.execute(
                "UPDATE auth_users SET username_index = ?, password_hash = ?, enc_nonce = ?,"
                " enc_ct = ?, key_id = ?, role = ?, active = ?, auth_version = ?,"
                " updated_at = ? WHERE user_id = ?",
                [
                    record.username_index,
                    record.password_hash,
                    bytes(record.enc_nonce),
                    bytes(record.enc_ct),
                    record.key_id,
                    record.role,
                    1 if record.active else 0,
                    record.auth_version,
                    record.updated_at,
                    record.user_id,
                ],
            )
            if cur.rowcount != 1:
                conn.execute("ROLLBACK", [])
                conn.close()
                raise StoreUnavailable()
            conn.execute("COMMIT", [])
        except ContractError:
            raise
        except sqlite3.IntegrityError as exc:
            try:
                conn.execute("ROLLBACK", [])
            except sqlite3.Error:
                pass
            conn.close()
            raise ContractError(code="duplicate_id", message="user exists") from exc
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK", [])
            except sqlite3.Error:
                pass
            conn.close()
            raise StoreUnavailable() from exc
        conn.close()
