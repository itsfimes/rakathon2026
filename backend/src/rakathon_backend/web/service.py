from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from rakathon_backend.b5.safety import configured_kill_file, kill_requested
from rakathon_backend.common.collection import (
    MAX_COLLECTION,
    MAX_FACTS,
    checked_metadata,
    failure_metadata,
)
from rakathon_backend.common.contracts import DataKind
from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.rpc import new_envelope
from rakathon_backend.runtime.application import BackendApp
from rakathon_backend.web.assistant import WebAssistant
from rakathon_backend.web.contracts import Client, WebError
from rakathon_backend.web.projection import (
    MAX_ITEMS,
    ProjectionError,
    belongs_to,
    patient_summary,
    project,
)

SECTIONS = {
    "conditions": "Condition",
    "observations": "Observation",
    "diagnosticReports": "DiagnosticReport",
    "documents": "DocumentReference",
}
UPSTREAM_FAILURES = (OSError, ValueError, RuntimeError, TypeError, KeyError, AttributeError)
MAX_SECTION_BYTES = 192 * 1024
MAX_OBSERVATION_BYTES = 256 * 1024
MAX_PATIENT_BYTES = 64 * 1024


__all__ = ["Client", "WebError"]


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def total_of(payload: dict[str, Any]) -> int | None:
    total = payload.get("serverTotal")
    if total is None:
        return None
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ProjectionError("invalid total")
    return total


def resources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    bundle = payload.get("bundle")
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise ProjectionError("invalid bundle")
    entries = bundle.get("entry")
    if not isinstance(entries, list) or len(entries) > MAX_COLLECTION:
        raise ContractError(code="resource_limit", message="Collection too large")
    if any(
        isinstance(link, dict) and link.get("relation") == "next" for link in bundle.get("link", [])
    ):
        raise ContractError(code="truncated", message="Collection incomplete")
    result = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict):
            raise ProjectionError("invalid entry")
        result.append(entry["resource"])
    return result


class WebService:
    def __init__(
        self,
        client: Client,
        assistant_client: Client | None = None,
        assistant_ready: Callable[[], bool] = lambda: True,
        *,
        binding_key: bytes | None = None,
        binding_clock: Callable[[], float] | None = None,
    ) -> None:
        self.client = client
        self._slots = asyncio.Semaphore(4)
        self.assistant: WebAssistant | None
        if assistant_client is not None:
            self.assistant = WebAssistant(
                assistant_client,
                self._case,
                binding_key=binding_key,
                binding_clock=binding_clock,
            )
        else:
            self.assistant = None
        self.assistant_ready = assistant_ready

    @classmethod
    def from_app(cls, app: BackendApp, assistant_enabled: bool = False) -> WebService:
        if assistant_enabled and app.ai_mode != "direct":
            raise ValueError("Web assistant requires direct mode")
        return cls(
            app.frontend_client("viewer"),
            app.frontend_client("web-assistant") if assistant_enabled else None,
            lambda: (
                app.gateway is not None
                and app.gateway.mode == "direct"
                and not app.kill_switch.tripped
                and not kill_requested(configured_kill_file())
            ),
        )

    async def _read(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = new_envelope(
            source="frontend:viewer",
            target="b4",
            action="fhir.read",
            data_kind=DataKind.FHIR,
            payload=payload,
            user_id="viewer",
        )
        async with self._slots:
            async with asyncio.timeout(7):
                reply = await self.client.call(request, expect_source="b4")
        if reply.payload.get("mode") != "iris-fhir":
            raise ProjectionError("unexpected storage")
        return reply.payload

    async def session(self) -> tuple[int, dict[str, Any]]:
        ipc = "down"
        database = "down"
        try:
            async with asyncio.timeout(7):
                health = await self.client.ping("b4")
            if health.value == "HEALTHY":
                ipc = "up"
        except UPSTREAM_FAILURES:
            ipc = "down"
        try:
            payload = await self._read({"resourceType": "Patient", "_summary": "count"})
            if total_of(payload) is not None:
                database = "up"
        except UPSTREAM_FAILURES:
            database = "down"
        return 200, {
            "version": 1,
            "access": "single-user-development",
            "storage": "iris-fhir",
            "capabilities": {
                "workspaceRead": True,
                "caseRead": True,
                "tasks": False,
                "vectors": False,
                "ingestion": False,
                "screening": False,
                "assistant": self.assistant is not None
                and self.assistant_ready()
                and ipc == "up"
                and database == "up",
            },
            "health": {"ipc": ipc, "database": database},
        }

    async def workspace(self) -> tuple[int, dict[str, Any]]:
        total = None
        try:
            payload = await self._read({"resourceType": "Patient", "_count": str(MAX_ITEMS)})
            total = total_of(payload)
            patients = [patient_summary(item) for item in resources(payload)]
            if len({item["patientId"] for item in patients}) != len(patients):
                raise ProjectionError("duplicate patient")
        except UPSTREAM_FAILURES as exc:
            return 503, {
                "version": 1,
                "fetchedAt": timestamp(),
                "patients": [],
                "coverage": {
                    "status": "unavailable",
                    **failure_metadata(exc),
                    "serverTotal": getattr(exc, "metadata", {}).get("serverTotal", total),
                },
            }
        return 200, {
            "version": 1,
            "fetchedAt": timestamp(),
            "patients": patients,
            "coverage": {
                "status": "complete",
                "serverTotal": total,
                "reason": None,
                "encounteredCount": None,
                "pagesFetched": None,
                **checked_metadata(payload.get("collection", {})),
                "receivedCount": len(patients),
            },
        }

    async def _section(self, resource_type: str, patient_id: str) -> dict[str, Any]:
        total = None
        metadata: dict[str, Any] = {}
        try:
            payload = await self._read(
                {
                    "resourceType": resource_type,
                    "patient": f"Patient/{patient_id}",
                    "_count": str(MAX_ITEMS),
                }
            )
            total = total_of(payload)
            items = resources(payload)
            metadata = {
                "encounteredCount": None,
                "pagesFetched": None,
                **checked_metadata(payload.get("collection", {})),
                "receivedCount": len(items),
                "serverTotal": total,
            }
            if any(not belongs_to(item, patient_id) for item in items):
                raise ContractError(
                    code="invalid_response", message="Association mismatch", metadata=metadata
                )
            if resource_type == "Observation" and any(
                not isinstance(item.get("component", []), list) for item in items
            ):
                raise ContractError(
                    code="invalid_response", message="Invalid components", metadata=metadata
                )
            if (
                resource_type == "Observation"
                and sum(1 + len(item.get("component", [])) for item in items) > MAX_FACTS
            ):
                raise ContractError(
                    code="resource_limit", message="Observation facts too large", metadata=metadata
                )
            projected = [project(item, resource_type) for item in items]
            if len({item["id"] for item in projected}) != len(projected):
                raise ContractError(
                    code="duplicate_resource", message="Duplicate resource", metadata=metadata
                )
            byte_limit = (
                MAX_OBSERVATION_BYTES if resource_type == "Observation" else MAX_SECTION_BYTES
            )
            if len(json.dumps(projected, ensure_ascii=True).encode()) > byte_limit:
                raise ContractError(
                    code="resource_limit", message="Section too large", metadata=metadata
                )
            return {"status": "complete", "items": projected, "reason": None, **metadata}
        except UPSTREAM_FAILURES as exc:
            failure = failure_metadata(exc)
            if metadata and not getattr(exc, "metadata", {}):
                failure.update(metadata)
            return {
                "status": "unavailable",
                "items": [],
                **failure,
            }

    async def case(self, patient_id: str) -> tuple[int, dict[str, Any]]:
        status, case = await self._case(patient_id)
        if self.assistant is not None and self.assistant_ready():
            case["assistantPreview"] = self.assistant.bindings.previews(case)
        return status, case

    async def send_assistant(self, request: Any) -> tuple[int, dict[str, Any]]:
        if self.assistant is None or not self.assistant_ready():
            raise WebError(503, "unavailable", "Assistant is not configured")
        return await self.assistant.send(request)

    async def _case(self, patient_id: str) -> tuple[int, dict[str, Any]]:
        try:
            payload = await self._read({"resourceType": "Patient", "id": patient_id})
            items = resources(payload)
            if not items:
                raise WebError(404, "not_found", "Case not found")
            if len(items) != 1 or items[0].get("id") != patient_id:
                raise ProjectionError("identity mismatch")
            patient = project(items[0], "Patient")
            if len(json.dumps(patient, ensure_ascii=True).encode()) > MAX_PATIENT_BYTES:
                raise ProjectionError("patient too large")
        except WebError:
            raise
        except Exception as exc:
            raise WebError(503, "unavailable", "Case unavailable") from exc
        sections = await asyncio.gather(
            *(self._section(kind, patient_id) for kind in SECTIONS.values())
        )
        return 200, {
            "version": 1,
            "fetchedAt": timestamp(),
            "patient": patient,
            "sections": dict(zip(SECTIONS, sections, strict=True)),
        }
