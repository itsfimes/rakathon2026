from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from rakathon_backend.common.errors import ContractError

TASK_STATUSES = frozenset({"OPEN", "ACKED", "DONE"})


def parse_due(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ContractError(code="bad_payload", message="dueAt must carry timezone")
    return parsed.astimezone(UTC)


def _task_id(payload: dict[str, Any]) -> str:
    task_id = payload.get("id") or f"task-{uuid.uuid4().hex[:8]}"
    if not isinstance(task_id, str) or not task_id.strip():
        raise ContractError(code="bad_payload", message="task id invalid")
    return task_id.strip()


def _owner(payload: dict[str, Any]) -> str:
    owner = payload.get("ownerId")
    if not isinstance(owner, str) or not owner.strip():
        raise ContractError(code="bad_payload", message="ownerId is required")
    return owner.strip()


def _required(payload: dict[str, Any], owner: str) -> list[str]:
    required = payload.get("requiredAckUserIds", [owner])
    if not isinstance(required, list) or not required:
        raise ContractError(code="bad_payload", message="requiredAckUserIds invalid")
    for item in required:
        if not isinstance(item, str) or not item.strip():
            raise ContractError(code="bad_payload", message="requiredAckUserIds invalid")
    return [str(x).strip() for x in required]


def _patient_ref(payload: dict[str, Any]) -> str | None:
    patient_ref = payload.get("patientRef")
    if patient_ref is not None and (not isinstance(patient_ref, str) or not patient_ref.strip()):
        raise ContractError(code="bad_payload", message="patientRef invalid")
    return patient_ref


def _strict_version(payload: dict[str, Any]) -> int:
    raw = payload.get("version", 1)
    if type(raw) is not int or isinstance(raw, bool):
        raise ContractError(code="bad_payload", message="version must be an integer")
    if raw < 1:
        raise ContractError(code="bad_payload", message="version invalid")
    return raw


def normalize_task_state(payload: dict[str, Any]) -> dict[str, Any]:
    task_id = _task_id(payload)
    owner = _owner(payload)
    due_raw = payload.get("dueAt")
    if not isinstance(due_raw, str) or not due_raw.strip():
        raise ContractError(code="bad_payload", message="dueAt is required")
    due = parse_due(due_raw)
    status = str(payload.get("status", "OPEN"))
    if status not in TASK_STATUSES:
        raise ContractError(code="bad_payload", message="task status invalid")
    required = _required(payload, owner)
    acked = payload.get("acknowledgedBy", [])
    if not isinstance(acked, list):
        raise ContractError(code="bad_payload", message="acknowledgedBy invalid")
    for item in acked:
        if not isinstance(item, str) or not item.strip():
            raise ContractError(code="bad_payload", message="acknowledgedBy invalid")
    return {
        "id": task_id,
        "ownerId": owner,
        "dueAt": due.isoformat(),
        "status": status,
        "requiredAckUserIds": required,
        "acknowledgedBy": [str(x) for x in acked],
        "patientRef": _patient_ref(payload),
        "version": _strict_version(payload),
    }


def validate_public_task_create(payload: dict[str, Any]) -> dict[str, Any]:
    raw_status = payload.get("status", "OPEN")
    if not isinstance(raw_status, str) or raw_status != "OPEN":
        raise ContractError(code="forged_state", message="public create must start OPEN")
    raw_acked = payload.get("acknowledgedBy", [])
    if not isinstance(raw_acked, list) or len(raw_acked) != 0:
        raise ContractError(code="forged_state", message="public create takes no acks")
    if "version" in payload and type(payload.get("version")) is not int:
        raise ContractError(code="bad_payload", message="version must be an integer")
    if "version" in payload and payload.get("version") != 1:
        raise ContractError(code="forged_state", message="public create starts at version 1")
    task = normalize_task_state(payload)
    task["status"] = "OPEN"
    task["acknowledgedBy"] = []
    task["version"] = 1
    return task


def is_ack_member(task: dict[str, Any], user_id: str) -> bool:
    if not isinstance(user_id, str) or not user_id:
        return False
    if task.get("ownerId") == user_id:
        return True
    required = task.get("requiredAckUserIds", [])
    return isinstance(required, list) and user_id in required
