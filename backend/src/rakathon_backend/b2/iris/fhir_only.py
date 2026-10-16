from __future__ import annotations

import contextlib
from typing import Any

from rakathon_backend.b2.iris.fhir import DirectFhirAdapter
from rakathon_backend.common.errors import ContractError


class FhirOnlyStorage:
    def __init__(self, fhir: DirectFhirAdapter) -> None:
        self._fhir = fhir

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
        return self._fhir.search_with_total(resource_type, dict(params))

    def tasks_create(self, task: dict[str, Any]) -> dict[str, Any]:
        _ = task
        raise ContractError(code="not_configured", message="tasks are not configured")

    def tasks_write(self, task: dict[str, Any]) -> dict[str, Any]:
        _ = task
        raise ContractError(code="not_configured", message="tasks are not configured")

    def tasks_read(self, task_id: str | None = None) -> list[dict[str, Any]]:
        _ = task_id
        raise ContractError(code="not_configured", message="tasks are not configured")

    def tasks_ack(self, task_id: str, user_id: str) -> dict[str, Any]:
        _ = (task_id, user_id)
        raise ContractError(code="not_configured", message="tasks are not configured")

    def vector_search(self, channel: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        _ = (channel, query, limit)
        raise ContractError(code="not_configured", message="vector not configured")

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._fhir.close()
