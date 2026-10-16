from __future__ import annotations

from typing import Any

from rakathon_backend.b2.screening import schema
from rakathon_backend.b2.screening.ports import ScreeningPage
from rakathon_backend.b2.screening.reader import ResolvedSource, iter_validated_rows
from rakathon_backend.common.errors import ContractError

MAX_LIMIT = 500
MAX_OFFSET = 2000000
MAX_FILTER_VALUE = 256
MAX_FILTERS = 12


def check_query_args(
    filters: Any, projection: Any, limit: Any, offset: Any
) -> tuple[dict[str, str], list[str], int, int]:
    if not isinstance(filters, dict):
        raise ContractError(code="bad_payload", message="filters must be an object")
    if len(filters) > MAX_FILTERS:
        raise ContractError(code="bad_payload", message="too many filters")
    clean_filters: dict[str, str] = {}
    for key, value in filters.items():
        if not isinstance(key, str) or key not in schema.FILTERABLE:
            raise ContractError(code="bad_payload", message="filter field is not allowed")
        if not isinstance(value, str) or not value or len(value) > MAX_FILTER_VALUE:
            raise ContractError(code="bad_payload", message="filter value invalid")
        clean_filters[key] = value
    if projection is None:
        clean_projection = list(schema.HEADER)
    else:
        if not isinstance(projection, list) or not projection:
            raise ContractError(code="bad_payload", message="projection invalid")
        if len(projection) > len(schema.HEADER):
            raise ContractError(code="bad_payload", message="projection invalid")
        seen: set[str] = set()
        clean_projection = []
        for item in projection:
            if not isinstance(item, str) or item not in schema.COLUMNS or item in seen:
                raise ContractError(code="bad_payload", message="projection field not allowed")
            seen.add(item)
            clean_projection.append(item)
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ContractError(code="bad_payload", message="limit invalid")
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ContractError(code="bad_payload", message="offset invalid")
    if limit < 1 or limit > MAX_LIMIT:
        raise ContractError(code="bad_payload", message="limit out of bounds")
    if offset < 0 or offset > MAX_OFFSET:
        raise ContractError(code="bad_payload", message="offset out of bounds")
    return (clean_filters, clean_projection, limit, offset)


class ArchiveScreeningStore:
    def __init__(self, resolved: ResolvedSource, member_override: str | None = None) -> None:
        self._resolved = resolved
        self._member = member_override

    @property
    def member(self) -> str | None:
        return self._member or self._resolved.member

    def describe(self) -> dict[str, Any]:
        return {
            "backend": "archive",
            "columns": list(schema.HEADER),
            "filterable": sorted(schema.FILTERABLE),
            "maxLimit": MAX_LIMIT,
            "maxOffset": MAX_OFFSET,
            "order": "file-order",
        }

    def query(
        self,
        filters: dict[str, str],
        projection: list[str] | None,
        limit: int,
        offset: int,
    ) -> ScreeningPage:
        wanted, columns, want, skip = check_query_args(filters, projection, limit, offset)
        rows: list[dict[str, str]] = []
        skipped = 0
        matched = 0
        truncated = False
        stream = iter_validated_rows(self._resolved, self._member)
        try:
            for _lineno, record in stream:
                hit = True
                for key, value in wanted.items():
                    if record[key] != value:
                        hit = False
                        break
                if not hit:
                    continue
                if skipped < skip:
                    skipped += 1
                    continue
                matched += 1
                if len(rows) <= want:
                    rows.append({column: record[column] for column in columns})
                if matched > want:
                    truncated = True
                    break
        finally:
            stream.close()
        return ScreeningPage(rows=rows[:want], offset=skip, limit=want, truncated=truncated)
