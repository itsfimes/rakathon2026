from __future__ import annotations

from rakathon_backend.common.contracts import DataKind

_REQUEST_KINDS: dict[str, DataKind] = {
    "ingest": DataKind.PROPRIETARY,
    "fhir.read": DataKind.METADATA,
    "fhir.search": DataKind.METADATA,
    "screening.query": DataKind.METADATA,
    "fhir.write": DataKind.FHIR,
    "document.approve": DataKind.FHIR,
    "tasks.read": DataKind.METADATA,
    "tasks.write": DataKind.PROPRIETARY,
    "tasks.ack": DataKind.METADATA,
    "vector.anonymized.search": DataKind.PROPRIETARY,
    "vector.patient.search": DataKind.PROPRIETARY,
    "ai.complete": DataKind.PROPRIETARY,
    "ai.translate": DataKind.PROPRIETARY,
    "reminders.read": DataKind.METADATA,
    "watchdog.tick": DataKind.METADATA,
    "health": DataKind.METADATA,
}


def request_kind(action: str) -> DataKind:
    return _REQUEST_KINDS.get(action, DataKind.METADATA)
