from __future__ import annotations

from collections import deque
from typing import Any

from rakathon_backend.common.errors import ContractError

CAPACITY = 500


def check_reminder(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ContractError(code="bad_payload", message="reminder invalid")
    task_id = item.get("taskId")
    rid = item.get("id", task_id)
    owner = item.get("ownerId")
    required = item.get("requiredAckUserIds", [])
    if not isinstance(task_id, str) or not task_id.strip():
        raise ContractError(code="bad_payload", message="reminder taskId invalid")
    if not isinstance(rid, str) or not rid.strip():
        raise ContractError(code="bad_payload", message="reminder id invalid")
    if not isinstance(owner, str) or not owner.strip():
        raise ContractError(code="bad_payload", message="reminder ownerId invalid")
    if not isinstance(required, list):
        raise ContractError(code="bad_payload", message="reminder ack list invalid")
    for user in required:
        if not isinstance(user, str) or not user.strip():
            raise ContractError(code="bad_payload", message="reminder ack list invalid")
    clean = dict(item)
    clean["id"] = rid.strip()
    clean["taskId"] = task_id.strip()
    clean["ownerId"] = owner.strip()
    return clean


class ReminderStore:
    def __init__(self, capacity: int = CAPACITY) -> None:
        if capacity <= 0 or capacity > 5000:
            raise ValueError("reminder capacity out of bounds")
        self._items: deque[dict[str, Any]] = deque(maxlen=capacity)

    def __len__(self) -> int:
        return len(self._items)

    def store_all(self, items: list[Any]) -> int:
        checked = [check_reminder(item) for item in items]
        for reminder in checked:
            self._upsert(reminder)
        return len(checked)

    def _upsert(self, reminder: dict[str, Any]) -> None:
        for index, current in enumerate(self._items):
            if current.get("taskId") == reminder.get("taskId"):
                self._items[index] = reminder
                return
        self._items.append(reminder)

    def visible(
        self, user_id: str, privileged: frozenset[str], owner_filter: str | None
    ) -> list[dict[str, Any]]:
        if user_id in privileged:
            items = list(self._items)
            if isinstance(owner_filter, str) and owner_filter.strip():
                items = [r for r in items if r.get("ownerId") == owner_filter.strip()]
            return items
        own = [
            r
            for r in self._items
            if r.get("ownerId") == user_id or user_id in list(r.get("requiredAckUserIds", []))
        ]
        if isinstance(owner_filter, str) and owner_filter.strip() and owner_filter != user_id:
            return own
        if isinstance(owner_filter, str) and owner_filter.strip():
            return [r for r in own if r.get("ownerId") == owner_filter.strip()]
        return own
