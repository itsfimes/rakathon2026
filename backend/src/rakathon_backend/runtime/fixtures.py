from __future__ import annotations

from typing import Any


def complete_fixture() -> dict[str, Any]:
    return {
        "synthetic": True,
        "patient": {"id": "pat-demo-001", "name": "Demo Patient One"},
        "referralReason": "Synthetic cardiology review",
    }


def incomplete_fixture() -> dict[str, Any]:
    return {
        "synthetic": True,
        "patient": {"id": "", "name": ""},
        "referralReason": "",
    }


def overdue_task(owner: str = "clinician") -> dict[str, Any]:
    return {
        "id": "task-demo-overdue-1",
        "ownerId": owner,
        "dueAt": "2000-01-01T00:00:00+00:00",
        "status": "OPEN",
        "requiredAckUserIds": [owner],
        "acknowledgedBy": [],
        "patientRef": "Patient/pat-demo-001",
        "version": 1,
    }
