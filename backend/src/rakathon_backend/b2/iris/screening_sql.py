from __future__ import annotations

import contextlib
from typing import Any

from rakathon_backend.b2.iris import task_sql
from rakathon_backend.b2.iris.config import IrisSqlConfig
from rakathon_backend.b2.iris.task_sql import Factory
from rakathon_backend.b2.screening import archive, schema
from rakathon_backend.common.errors import ContractError

SCREENING_TABLE = "Screening"
MAX_BATCH = 500
MAX_IRIS_OFFSET = 5000
INVITATION_ID_WIDTH = 64

LENGTHS: dict[str, int] = {
    "INVITATION_ID": INVITATION_ID_WIDTH,
    "PERSON_ID": 32,
    "INVITATION_DATE": 16,
    "AGE_BAND": 16,
    "VZP_TERRITORIAL_AREA": 64,
    "PRIOR_INVITATION_COUNT": 16,
    "MONTHS_LAST_INVITATION": 16,
    "INVITATION_SEQUENCE": 16,
    "HEALTHCARE_CONTACT_12M_CNT": 16,
    "FIRST_INVITATION": 4,
    "INSURANCE_DURATION_YEARS": 16,
    "GP_REGISTERED": 4,
    "GP_REG_DURATION_BAND": 16,
    "GYN_REGISTERED_FLAG": 4,
    "GYN_REG_DURATION_BAND": 16,
    "PRIOR_SCREEN_COUNT_5Y": 16,
    "MONTHS_SINCE_LAST_SCREEN": 16,
    "NEVER_SCREENED_BEFORE_FLAG": 4,
    "GP_PREVENTION_24M_CNT": 16,
    "GYN_PREVENTION_24M_CNT": 16,
    "OTHER_SCREENING_36M_CNT": 16,
    "DENTAL_PREVENTION_24M_CNT": 16,
    "SCREENING_3M_FLAG": 4,
    "SCREENING_6M_FLAG": 4,
    "SCREENING_12M_FLAG": 4,
}

COLUMNS_SQL = ", ".join(f"{name} VARCHAR({LENGTHS[name]})" for name in schema.HEADER)


class ScreeningSqlStore:
    def __init__(
        self,
        sql_config: IrisSqlConfig,
        factory: Factory | None = None,
        table: str = SCREENING_TABLE,
    ) -> None:
        self._sql = sql_config
        self._factory = factory or (lambda: task_sql.default_connect(sql_config))
        self._table = task_sql.ident(table, "table")
        self._schema = task_sql.ident(sql_config.schema, "schema")

    def qualified(self) -> str:
        return task_sql.qualified_table(self._schema, self._table)

    def init_db(self) -> dict[str, str]:
        qualified = self.qualified()
        conn = self._factory()
        try:
            cur = conn.cursor()
            cur.execute(f"CREATE TABLE {qualified} ({COLUMNS_SQL}, PRIMARY KEY (INVITATION_ID))")
            conn.commit()
        except Exception as exc:
            with contextlib.suppress(Exception):
                conn.rollback()
            raise ContractError(code="remote_error", message="init failed") from exc
        finally:
            with contextlib.suppress(Exception):
                conn.close()
        return {"table": qualified, "status": "created"}

    def _existing(self, conn: Any, qualified: str, invitation_id: str) -> dict[str, str] | None:
        cur = conn.cursor()
        names = ", ".join(schema.HEADER)
        cur.execute(
            f"SELECT TOP 1 {names} FROM {qualified} WHERE INVITATION_ID = ?", [invitation_id]
        )
        row = cur.fetchone()
        if row is None:
            return None
        vals = list(row)
        return {name: str(vals[i]) for i, name in enumerate(schema.HEADER)}

    def import_batch(self, rows: list[dict[str, Any]]) -> dict[str, int]:
        if not isinstance(rows, list) or not rows or len(rows) > MAX_BATCH:
            raise ContractError(code="bad_payload", message="batch must hold 1..500 rows")
        checked: list[dict[str, str]] = []
        for item in rows:
            if not isinstance(item, dict):
                raise ContractError(code="bad_payload", message="screening row invalid")
            checked.append(schema.validate_row(item))
        qualified = self.qualified()
        conn = self._factory()
        imported = 0
        skipped = 0
        try:
            for record in checked:
                found = self._existing(conn, qualified, record["INVITATION_ID"])
                if found is None:
                    cur = conn.cursor()
                    placeholders = ", ".join(["?"] * len(schema.HEADER))
                    cur.execute(
                        f"INSERT INTO {qualified} ({', '.join(schema.HEADER)}) "
                        f"VALUES ({placeholders})",
                        [record[name] for name in schema.HEADER],
                    )
                    imported += 1
                elif all(found[name] == record[name] for name in schema.HEADER):
                    skipped += 1
                else:
                    raise ContractError(code="conflict", message="screening row differs")
            conn.commit()
        except ContractError:
            with contextlib.suppress(Exception):
                conn.rollback()
            raise
        except Exception as exc:
            with contextlib.suppress(Exception):
                conn.rollback()
            raise ContractError(code="remote_error", message="iris request failed") from exc
        finally:
            with contextlib.suppress(Exception):
                conn.close()
        return {"imported": imported, "skipped": skipped, "total": len(checked)}

    def query(
        self,
        filters: dict[str, str],
        projection: list[str] | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, str]]:
        wanted, columns, want, skip = archive.check_query_args(filters, projection, limit, offset)
        if skip > MAX_IRIS_OFFSET:
            raise ContractError(code="bad_payload", message="iris offset out of bounds")
        qualified = self.qualified()
        clauses: list[str] = []
        params: list[Any] = []
        for key, value in sorted(wanted.items()):
            clauses.append(f"{key} = ?")
            params.append(value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        top = want + skip
        conn = self._factory()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT TOP {top} {', '.join(columns)} FROM {qualified}{where}",
                params,
            )
            fetched = cur.fetchall()
        except ContractError:
            raise
        except Exception as exc:
            raise ContractError(code="remote_error", message="iris request failed") from exc
        finally:
            with contextlib.suppress(Exception):
                conn.close()
        out: list[dict[str, str]] = []
        for row in fetched[skip:]:
            vals = list(row)
            out.append({name: str(vals[i]) for i, name in enumerate(columns)})
        return out
