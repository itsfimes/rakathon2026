from __future__ import annotations

import contextlib
import sqlite3
import uuid
from collections.abc import Callable
from typing import Any

from rakathon_backend.b2.auth.models import RateLimited, StoreUnavailable

ALLOWED_SCOPES = frozenset({"acct", "glob"})
MAX_KEY_CHARS = 256
MAX_LIMIT = 10000


def new_reservation_id() -> str:
    return uuid.uuid4().hex


def check_claim_args(scope: str, key: str, limit: int) -> None:
    if scope not in ALLOWED_SCOPES:
        raise StoreUnavailable()
    if not isinstance(key, str) or not key or len(key) > MAX_KEY_CHARS:
        raise StoreUnavailable()
    if not isinstance(limit, int) or limit < 1 or limit > MAX_LIMIT:
        raise StoreUnavailable()


def claim_slot(
    cur: Any,
    rowcount: Callable[[Any], int],
    table: str,
    scope: str,
    key: str,
    limit: int,
    now: int,
    cutoff: int,
    reservation_id: str,
) -> int | None:
    check_claim_args(scope, key, limit)
    if not isinstance(now, int) or not isinstance(cutoff, int):
        raise StoreUnavailable()
    if not isinstance(reservation_id, str) or len(reservation_id) != 32:
        raise StoreUnavailable()
    for slot in range(limit):
        try:
            cur.execute(
                f"UPDATE {table} SET ts = ?, reservation_id = ?"
                " WHERE scope = ? AND key = ? AND slot = ? AND ts <= ?",
                [now, reservation_id, scope, key, slot, cutoff],
            )
        except (sqlite3.Error, OSError, ValueError, RuntimeError) as exc:
            raise StoreUnavailable() from exc
        try:
            matched = rowcount(cur)
        except StoreUnavailable:
            raise
        except (sqlite3.Error, OSError, ValueError, RuntimeError) as exc:
            raise StoreUnavailable() from exc
        if matched == 1:
            return slot
        if matched != 0:
            raise StoreUnavailable()
        try:
            cur.execute(
                f"INSERT INTO {table} (scope, key, slot, ts, reservation_id)"
                " VALUES (?, ?, ?, ?, ?)",
                [scope, key, slot, now, reservation_id],
            )
            return slot
        except (sqlite3.Error, OSError, ValueError, RuntimeError):
            with contextlib.suppress(Exception):
                cur.execute(
                    f"SELECT slot FROM {table} WHERE scope = ? AND key = ? AND slot = ?",
                    [scope, key, slot],
                )
                rows = cur.fetchall()
                if rows:
                    continue
            raise StoreUnavailable()
    return None


def release_slot(
    cur: Any,
    table: str,
    scope: str,
    key: str,
    slot: int,
    reservation_id: str,
) -> None:
    check_claim_args(scope, key, MAX_LIMIT)
    if not isinstance(slot, int) or slot < 0:
        raise StoreUnavailable()
    try:
        cur.execute(
            f"DELETE FROM {table} WHERE scope = ? AND key = ? AND slot = ? AND reservation_id = ?",
            [scope, key, slot, reservation_id],
        )
    except (sqlite3.Error, OSError, ValueError, RuntimeError) as exc:
        raise StoreUnavailable() from exc


def reserve_pair(
    cur: Any,
    rowcount: Callable[[Any], int],
    commit: Callable[[], None],
    rollback: Callable[[], None],
    table: str,
    account_key: str,
    now: int,
    account_limit: int,
    account_window: int,
    global_limit: int,
    global_window: int,
) -> None:
    if not isinstance(now, int):
        raise StoreUnavailable()
    if not isinstance(account_window, int) or not isinstance(global_window, int):
        raise StoreUnavailable()
    check_claim_args("acct", account_key, account_limit)
    check_claim_args("glob", "g", global_limit)
    acct_cutoff = now - account_window
    glob_cutoff = now - global_window
    acct_res = new_reservation_id()
    acct_slot = claim_slot(
        cur, rowcount, table, "acct", account_key, account_limit, now, acct_cutoff, acct_res
    )
    if acct_slot is None:
        with contextlib.suppress(Exception):
            rollback()
        raise RateLimited()
    try:
        commit()
    except (sqlite3.Error, OSError, ValueError, RuntimeError) as exc:
        raise StoreUnavailable() from exc
    glob_res = new_reservation_id()
    try:
        glob_slot = claim_slot(
            cur, rowcount, table, "glob", "g", global_limit, now, glob_cutoff, glob_res
        )
    except StoreUnavailable:
        with contextlib.suppress(Exception):
            release_slot(cur, table, "acct", account_key, acct_slot, acct_res)
        with contextlib.suppress(Exception):
            commit()
        raise
    if glob_slot is None:
        with contextlib.suppress(Exception):
            release_slot(cur, table, "acct", account_key, acct_slot, acct_res)
        with contextlib.suppress(Exception):
            commit()
        raise RateLimited()
    try:
        commit()
    except (sqlite3.Error, OSError, ValueError, RuntimeError) as exc:
        with contextlib.suppress(Exception):
            release_slot(cur, table, "acct", account_key, acct_slot, acct_res)
        with contextlib.suppress(Exception):
            release_slot(cur, table, "glob", "g", glob_slot, glob_res)
        with contextlib.suppress(Exception):
            commit()
        raise StoreUnavailable() from exc
