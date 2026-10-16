from __future__ import annotations

import contextlib
from typing import Any

from rakathon_backend.b2.iris.fhir import DirectFhirAdapter
from rakathon_backend.b2.iris.sql import IrisSqlStore
from rakathon_backend.common.errors import ContractError


class CompositeIrisStorage:
    def __init__(
        self, fhir: DirectFhirAdapter, sql: IrisSqlStore, screening: Any | None = None
    ) -> None:
        self._fhir = fhir
        self._sql = sql
        self._screening = screening

    def fhir_write(self, resource: dict[str, Any]) -> dict[str, Any]:
        return self._fhir.write(dict(resource))

    def fhir_transaction(self, bundle: dict[str, Any]) -> dict[str, Any]:
        return self._fhir.transaction(dict(bundle))

    def fhir_read(self, resource_type: str, rid: str) -> dict[str, Any] | None:
        return self._fhir.read(resource_type, rid)

    def fhir_search(self, resource_type: str, params: dict[str, str]) -> list[dict[str, Any]]:
        return self._fhir.search(resource_type, dict(params))

    def fhir_search_with_total(
        self, resource_type: str, params: dict[str, str]
    ) -> tuple[list[dict[str, Any]], int | None]:
        inner = getattr(self._fhir, "search_with_total", None)
        if callable(inner):
            paired: tuple[list[dict[str, Any]], int | None] = inner(resource_type, dict(params))
            return paired
        return (self._fhir.search(resource_type, dict(params)), None)

    def tasks_create(self, task: dict[str, Any]) -> dict[str, Any]:
        return self._sql.tasks_create(dict(task))

    def tasks_write(self, task: dict[str, Any]) -> dict[str, Any]:
        return self._sql.tasks_write(dict(task))

    def tasks_read(self, task_id: str | None = None) -> list[dict[str, Any]]:
        return self._sql.tasks_read(task_id)

    def tasks_ack(self, task_id: str, user_id: str) -> dict[str, Any]:
        return self._sql.tasks_ack(task_id, user_id)

    def vector_search(self, channel: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if channel == "anonymized":
            return self._sql.vector_search(channel, query, limit)
        refs = self._sql.vector_search(channel, query, limit)
        out: list[dict[str, Any]] = []
        for item in refs:
            rtype = item.get("resourceType")
            rid = item.get("resourceId")
            if not isinstance(rtype, str) or not isinstance(rid, str):
                continue
            try:
                found = self._fhir.read(rtype, rid)
            except ContractError:
                continue
            if found is not None:
                out.append({"resource": found, "synthetic": False})
        return out

    def schema_discover(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._sql.schema_discover(dict(args))

    @property
    def screening(self) -> Any | None:
        return self._screening

    def init_db(self) -> dict[str, str]:
        return self._sql.init_db()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._fhir.close()
