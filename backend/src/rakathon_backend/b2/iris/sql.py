from __future__ import annotations

import contextlib
import json
import math
from typing import Any

from rakathon_backend.b2.iris import task_sql
from rakathon_backend.b2.iris.config import IrisSqlConfig, VectorStoreConfig
from rakathon_backend.b2.iris.task_sql import Connection, Cursor, Factory
from rakathon_backend.common.errors import ContractError

_ = (Connection, Cursor, Factory)


def _top(limit: int) -> int:
    if not isinstance(limit, int) or limit <= 0 or limit > 50:
        raise ContractError(code="bad_payload", message="limit invalid")
    return limit


def _parse_vector(query: str, dims: int) -> str:
    try:
        items = json.loads(query)
    except Exception as exc:
        raise ContractError(code="bad_payload", message="vector query invalid") from exc
    if not isinstance(items, list) or len(items) != dims or not items:
        raise ContractError(code="bad_payload", message="vector dimensions mismatch")
    for value in items:
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ContractError(code="bad_payload", message="vector query invalid")
    return ",".join(str(float(v)) for v in items)


class IrisSqlStore:
    def __init__(
        self,
        sql_config: IrisSqlConfig,
        tasks_factory: Factory | None = None,
        anon_factory: Factory | None = None,
        patient_factory: Factory | None = None,
        tasks_table: str = "Tasks",
        anon: VectorStoreConfig | None = None,
        patient: VectorStoreConfig | None = None,
    ) -> None:
        self._sql = sql_config
        self._tasks_factory = tasks_factory or (lambda: task_sql.default_connect(sql_config))
        self._anon_factory = anon_factory
        self._patient_factory = patient_factory
        self._tasks_table = task_sql.ident(tasks_table, "table")
        self._tasks_schema = task_sql.ident(sql_config.schema, "schema")
        self._anon = anon
        self._patient = patient

    def _qualified_tasks(self) -> str:
        return task_sql.qualified_table(self._tasks_schema, self._tasks_table)

    def init_db(self) -> dict[str, str]:
        qualified = self._qualified_tasks()
        conn = self._tasks_factory()
        try:
            cur = conn.cursor()
            cur.execute(
                f"CREATE TABLE {qualified} (id VARCHAR(64) PRIMARY KEY, "
                "ownerId VARCHAR(64), dueAt VARCHAR(64), status VARCHAR(16), "
                "requiredAck VARCHAR(2000), ackedBy VARCHAR(2000), "
                "patientRef VARCHAR(128), version INTEGER)"
            )
            conn.commit()
        except Exception as exc:
            with contextlib.suppress(Exception):
                conn.rollback()
            raise ContractError(code="remote_error", message="init failed") from exc
        finally:
            with contextlib.suppress(Exception):
                conn.close()
        return {"table": qualified, "status": "created"}

    def tasks_create(self, task: dict[str, Any]) -> dict[str, Any]:
        return task_sql.tasks_create(self._tasks_factory, self._qualified_tasks(), dict(task))

    def tasks_write(self, task: dict[str, Any]) -> dict[str, Any]:
        return task_sql.tasks_write_upsert(self._tasks_factory, self._qualified_tasks(), dict(task))

    def tasks_read(self, task_id: str | None = None) -> list[dict[str, Any]]:
        return task_sql.tasks_read(self._tasks_factory, self._qualified_tasks(), task_id)

    def tasks_ack(self, task_id: str, user_id: str) -> dict[str, Any]:
        return task_sql.tasks_ack(self._tasks_factory, self._qualified_tasks(), task_id, user_id)

    def vector_search(self, channel: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        count = _top(limit)
        if channel == "anonymized":
            cfg = self._anon
            factory = self._anon_factory
            if cfg is None or factory is None or not cfg.enabled:
                raise LookupError("not_configured")
            if not cfg.schema or not cfg.table or cfg.dimensions <= 0:
                raise LookupError("not_configured")
            if not cfg.synthetic_only:
                raise ContractError(code="unsupported", message="real anon store refused")
            vec = _parse_vector(query, cfg.dimensions)
            qualified = task_sql.qualified_table(cfg.schema, cfg.table)
            conn = factory()
            try:
                cur = conn.cursor()
                cur.execute(
                    f"SELECT TOP {count} vectorId, payload FROM {qualified} "
                    "ORDER BY VECTOR_COSINE(vec, TO_VECTOR(?, FLOAT)) DESC",
                    [vec],
                )
                rows = cur.fetchall()
            except ContractError:
                raise
            except Exception as exc:
                raise ContractError(code="remote_error", message="iris request failed") from exc
            finally:
                with contextlib.suppress(Exception):
                    conn.close()
            return [{"vectorId": str(r[0]), "synthetic": True} for r in rows if len(list(r)) >= 1]
        if channel == "patient":
            cfg = self._patient
            factory = self._patient_factory
            if cfg is None or factory is None or not cfg.enabled:
                raise LookupError("not_configured")
            vec = _parse_vector(query, cfg.dimensions)
            qualified = task_sql.qualified_table(cfg.schema, cfg.table)
            conn = factory()
            try:
                cur = conn.cursor()
                cur.execute(
                    f"SELECT TOP {count} resourceType, resourceId FROM {qualified} "
                    "ORDER BY VECTOR_COSINE(vec, TO_VECTOR(?, FLOAT)) DESC",
                    [vec],
                )
                rows = cur.fetchall()
            except ContractError:
                raise
            except Exception as exc:
                raise ContractError(code="remote_error", message="iris request failed") from exc
            finally:
                with contextlib.suppress(Exception):
                    conn.close()
            return [
                {"resourceType": str(r[0]), "resourceId": str(r[1])}
                for r in rows
                if len(list(r)) >= 2
            ]
        raise ContractError(code="bad_payload", message="channel invalid")

    def schema_discover(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = str(args.get("kind", "tables"))
        schema = args.get("schema")
        table = args.get("table")
        conn = self._tasks_factory()
        try:
            cur = conn.cursor()
            if kind == "tables":
                cur.execute(
                    "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_SCHEMA = ?",
                    [self._tasks_schema],
                )
                rows = cur.fetchall()
                return {
                    "tables": [
                        {"schema": str(r[0]), "table": str(r[1])}
                        for r in rows
                        if str(r[0]) == self._tasks_schema
                    ]
                }
            if isinstance(schema, str) and isinstance(table, str):
                task_sql.ident(schema, "schema")
                task_sql.ident(table, "table")
                if schema != self._tasks_schema:
                    raise ContractError(code="auth_failed", message="schema out of scope")
                cur.execute(
                    "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
                    [schema, table],
                )
                rows = cur.fetchall()
                return {
                    "columns": [{"name": str(r[0]), "type": str(r[1])} for r in rows],
                }
            raise ContractError(code="bad_payload", message="schema discover needs names")
        except ContractError:
            raise
        except Exception as exc:
            raise ContractError(code="remote_error", message="iris request failed") from exc
        finally:
            with contextlib.suppress(Exception):
                conn.close()
