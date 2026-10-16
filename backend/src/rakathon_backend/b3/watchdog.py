from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any


def task_fingerprint(task: dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(task.get("id", "")),
            str(task.get("status", "")),
            str(task.get("dueAt", "")),
            str(task.get("version", "")),
            ",".join(sorted(str(x) for x in task.get("acknowledgedBy", []))),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def compute_reminders(
    tasks: list[dict[str, Any]], now: datetime, *, clock: Callable[[], datetime] | None = None
) -> list[dict[str, Any]]:
    current = clock() if clock is not None else now
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    out: list[dict[str, Any]] = []
    for task in tasks:
        status = str(task.get("status", "OPEN"))
        if status == "DONE":
            continue
        due_raw = str(task.get("dueAt", ""))
        text = due_raw.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            due = datetime.fromisoformat(text)
        except ValueError:
            continue
        if due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        required = {str(x) for x in task.get("requiredAckUserIds", [])}
        acked = {str(x) for x in task.get("acknowledgedBy", [])}
        missing = sorted(required - acked)
        overdue = due <= current
        if overdue and status != "DONE":
            out.append(
                {
                    "id": str(task.get("id")),
                    "taskId": str(task.get("id")),
                    "ownerId": str(task.get("ownerId", "")),
                    "requiredAckUserIds": [str(x) for x in task.get("requiredAckUserIds", [])],
                    "reason": "overdue",
                    "dueAt": due_raw,
                    "missingAck": missing,
                    "fingerprint": task_fingerprint(task),
                    "version": int(task.get("version", 1)),
                }
            )
        elif missing:
            out.append(
                {
                    "id": str(task.get("id")),
                    "taskId": str(task.get("id")),
                    "ownerId": str(task.get("ownerId", "")),
                    "requiredAckUserIds": [str(x) for x in task.get("requiredAckUserIds", [])],
                    "reason": "missing_ack",
                    "dueAt": due_raw,
                    "missingAck": missing,
                    "fingerprint": task_fingerprint(task),
                    "version": int(task.get("version", 1)),
                }
            )
    return out


class ReminderDeduper:
    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def filter_new(self, reminders: list[dict[str, Any]]) -> list[dict[str, Any]]:
        fresh: list[dict[str, Any]] = []
        for item in reminders:
            key = str(item.get("taskId"))
            fingerprint = str(item.get("fingerprint"))
            if self._seen.get(key) != fingerprint:
                fresh.append(item)
                self._seen[key] = fingerprint
        return fresh

    def snapshot(self) -> dict[str, str]:
        return dict(self._seen)
