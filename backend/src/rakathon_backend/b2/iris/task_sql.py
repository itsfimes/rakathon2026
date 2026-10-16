from __future__ import annotations

import contextlib
import importlib
import json
import re
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from rakathon_backend.b2.iris.config import IrisSqlConfig
from rakathon_backend.common.errors import AuthError, ContractError

_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
TABLE_LIMIT = 200
MAX_ACK_RETRIES = 5


class Cursor(Protocol):
    rowcount: int

    def execute(self, sql: str, params: Sequence[Any] | None = ...) -> Any: ...
    def fetchall(self) -> list[Any]: ...
    def fetchone(self) -> Any: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


Factory = Callable[[], Connection]


def ident(value: str, label: str) -> str:
    if not isinstance(value, str) or _IDENT_RE.fullmatch(value) is None:
        raise ContractError(code="bad_payload", message=f"{label} invalid")
    return value


def qualified_table(schema: str, table: str) -> str:
    return f"{ident(schema, 'schema')}.{ident(table, 'table')}"


def default_connect(sql: IrisSqlConfig) -> Connection:
    try:
        module = importlib.import_module("iris.dbapi")
    except ImportError as exc:
        raise ContractError(code="not_configured", message="iris driver is not installed") from exc
    connect = getattr(module, "connect", None)
    if not callable(connect):
        raise ContractError(code="not_configured", message="iris driver has no connect")
    try:
        conn: Connection = connect(
            hostname=sql.host,
            port=sql.port,
            namespace=sql.namespace,
            username=sql.username,
            password=sql.password,
            sharedmemory=False,
            timeout=10000,
        )
        return conn
    except ContractError:
        raise
    except Exception as exc:
        raise ContractError(code="remote_error", message="iris connect failed") from exc


def make_factory(sql: IrisSqlConfig) -> Factory:
    def factory() -> Connection:
        return default_connect(sql)

    return factory


def _close(conn: Connection) -> None:
    with contextlib.suppress(Exception):
        conn.close()


def _rowcount(cur: Cursor, conn: Connection) -> int:
    raw = getattr(cur, "rowcount", None)
    if type(raw) is bool or not isinstance(raw, int):
        with contextlib.suppress(Exception):
            conn.rollback()
        raise ContractError(code="remote_error", message="iris request failed")
    return raw


def row_to_task(row: Any) -> dict[str, Any]:
    vals = list(row) if isinstance(row, (list, tuple)) else []
    while len(vals) < 8:
        vals.append("")
    try:
        required = json.loads(str(vals[4])) if vals[4] else []
        acked = json.loads(str(vals[5])) if vals[5] else []
    except ValueError:
        required = []
        acked = []
    return {
        "id": str(vals[0]),
        "ownerId": str(vals[1]),
        "dueAt": str(vals[2]),
        "status": str(vals[3]),
        "requiredAckUserIds": required if isinstance(required, list) else [],
        "acknowledgedBy": acked if isinstance(acked, list) else [],
        "patientRef": str(vals[6]) or None,
        "version": int(vals[7]) if str(vals[7]).lstrip("-").isdigit() else 1,
    }


def _params(task: dict[str, Any]) -> list[Any]:
    tid = str(task.get("id", ""))
    if not tid:
        raise ContractError(code="bad_payload", message="task id invalid")
    return [
        tid,
        str(task.get("ownerId", "")),
        str(task.get("dueAt", "")),
        str(task.get("status", "OPEN")),
        json.dumps(list(task.get("requiredAckUserIds", []))),
        json.dumps(list(task.get("acknowledgedBy", []))),
        str(task.get("patientRef") or ""),
        int(task.get("version", 1)),
    ]


def _exists(conn: Connection, qualified: str, tid: str) -> bool:
    cur = conn.cursor()
    cur.execute(f"SELECT TOP 1 id FROM {qualified} WHERE id = ?", [tid])
    return cur.fetchone() is not None


def tasks_create(factory: Factory, qualified: str, task: dict[str, Any]) -> dict[str, Any]:
    params = _params(task)
    conn = factory()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                f"INSERT INTO {qualified} (id, ownerId, dueAt, status, "
                "requiredAck, ackedBy, patientRef, version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                params,
            )
        except Exception as exc:
            with contextlib.suppress(Exception):
                conn.rollback()
            if _exists(conn, qualified, params[0]):
                raise ContractError(code="duplicate_id", message="task already exists") from exc
            raise ContractError(code="remote_error", message="iris request failed") from exc
        conn.commit()
    except ContractError:
        raise
    except Exception as exc:
        with contextlib.suppress(Exception):
            conn.rollback()
        raise ContractError(code="remote_error", message="iris request failed") from exc
    finally:
        _close(conn)
    return dict(task)


def tasks_write_upsert(factory: Factory, qualified: str, task: dict[str, Any]) -> dict[str, Any]:
    params = _params(task)
    conn = factory()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                f"UPDATE {qualified} SET ownerId = ?, dueAt = ?, status = ?, "
                "requiredAck = ?, ackedBy = ?, patientRef = ?, version = ? WHERE id = ?",
                [
                    params[1],
                    params[2],
                    params[3],
                    params[4],
                    params[5],
                    params[6],
                    params[7],
                    params[0],
                ],
            )
            updated = _rowcount(cur, conn)
            if updated == 0:
                cur.execute(
                    f"INSERT INTO {qualified} (id, ownerId, dueAt, status, "
                    "requiredAck, ackedBy, patientRef, version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    params,
                )
            conn.commit()
        except ContractError:
            raise
        except Exception as exc:
            with contextlib.suppress(Exception):
                conn.rollback()
            raise ContractError(code="remote_error", message="iris request failed") from exc
    except ContractError:
        raise
    except Exception as exc:
        with contextlib.suppress(Exception):
            conn.rollback()
        raise ContractError(code="remote_error", message="iris request failed") from exc
    finally:
        _close(conn)
    return dict(task)


def tasks_read(factory: Factory, qualified: str, task_id: str | None) -> list[dict[str, Any]]:
    conn = factory()
    try:
        cur = conn.cursor()
        if task_id is not None:
            cur.execute(
                f"SELECT TOP 1 id, ownerId, dueAt, status, requiredAck, ackedBy, "
                f"patientRef, version FROM {qualified} WHERE id = ?",
                [task_id],
            )
        else:
            cur.execute(
                f"SELECT TOP {TABLE_LIMIT} id, ownerId, dueAt, status, requiredAck, "
                f"ackedBy, patientRef, version FROM {qualified}"
            )
        rows = cur.fetchall()
    except ContractError:
        raise
    except Exception as exc:
        raise ContractError(code="remote_error", message="iris request failed") from exc
    finally:
        _close(conn)
    return [row_to_task(row) for row in rows]


def _ack_update(task: dict[str, Any], user_id: str) -> tuple[list[str], str, int] | None:
    if task.get("ownerId") != user_id and user_id not in list(task.get("requiredAckUserIds", [])):
        raise AuthError(code="auth_failed", message="user is not a task member")
    acked = list(task.get("acknowledgedBy", []))
    if user_id in acked:
        return None
    acked.append(user_id)
    required = set(task.get("requiredAckUserIds", []))
    status = str(task.get("status", "OPEN"))
    if required and set(acked) >= required:
        status = "ACKED"
    return (acked, status, int(task.get("version", 1)) + 1)


def tasks_ack(factory: Factory, qualified: str, task_id: str, user_id: str) -> dict[str, Any]:
    last: dict[str, Any] | None = None
    for _ in range(MAX_ACK_RETRIES + 1):
        conn = factory()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"SELECT TOP 1 id, ownerId, dueAt, status, requiredAck, ackedBy, "
                    f"patientRef, version FROM {qualified} WHERE id = ?",
                    [task_id],
                )
                rows = cur.fetchall()
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.rollback()
                raise ContractError(code="remote_error", message="iris request failed") from exc
            if not rows:
                with contextlib.suppress(Exception):
                    conn.rollback()
                raise KeyError(task_id)
            task = row_to_task(rows[0])
            last = task
            try:
                computed = _ack_update(task, user_id)
            except AuthError:
                with contextlib.suppress(Exception):
                    conn.rollback()
                raise
            if computed is None:
                with contextlib.suppress(Exception):
                    conn.rollback()
                return task
            acked, status, version = computed
            try:
                cur.execute(
                    f"UPDATE {qualified} SET ackedBy = ?, status = ?, version = ? "
                    "WHERE id = ? AND version = ?",
                    [json.dumps(acked), status, version, task_id, int(task.get("version", 1))],
                )
                matched = _rowcount(cur, conn)
            except ContractError:
                raise
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.rollback()
                raise ContractError(code="remote_error", message="iris request failed") from exc
            if matched == 1:
                try:
                    conn.commit()
                except Exception as exc:
                    with contextlib.suppress(Exception):
                        conn.rollback()
                    raise ContractError(code="remote_error", message="iris request failed") from exc
                return {
                    **task,
                    "acknowledgedBy": acked,
                    "status": status,
                    "version": version,
                }
            with contextlib.suppress(Exception):
                conn.rollback()
        finally:
            _close(conn)
    _ = last
    raise ContractError(code="conflict", message="task changed concurrently")
