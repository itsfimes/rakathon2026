from __future__ import annotations

import contextvars
import threading
from dataclasses import dataclass, field
from typing import Any

REASONS = frozenset(
    {
        "upstream_error",
        "auth_failed",
        "invalid_response",
        "unsafe_paging_link",
        "paging_cycle",
        "duplicate_resource",
        "inconsistent_total",
        "deadline_exceeded",
        "resource_limit",
        "truncated",
    }
)
MAX_COLLECTION = 500
MAX_FACTS = 1000


def checked_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {
        "reason",
        "receivedCount",
        "encounteredCount",
        "pagesFetched",
        "serverTotal",
    }:
        raise ValueError("Invalid collection metadata")
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key == "reason":
            if not isinstance(item, str) or item not in REASONS:
                raise ValueError("Invalid collection reason")
        elif item is not None:
            maximum = (
                2**53 - 1
                if key == "serverTotal"
                else 10
                if key == "pagesFetched"
                else MAX_COLLECTION + (key == "encounteredCount")
            )
            if type(item) is not int or not 0 <= item <= maximum:
                raise ValueError("Invalid collection counter")
        result[key] = item
    return result


@dataclass
class CollectionState:
    cancelled: threading.Event = field(default_factory=threading.Event)
    received: int = 0
    encountered: int = 0
    pages: int = 0
    total: int | None = None

    def metadata(self, reason: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "receivedCount": self.received,
            "encounteredCount": self.encountered,
            "pagesFetched": self.pages,
            "serverTotal": self.total,
        }
        if reason is not None:
            result["reason"] = reason
        return checked_metadata(result)


ACTIVE_COLLECTION: contextvars.ContextVar[CollectionState | None] = contextvars.ContextVar(
    "fhir_collection", default=None
)


def failure_metadata(exc: Exception) -> dict[str, Any]:
    metadata = checked_metadata(getattr(exc, "metadata", {}))
    code = getattr(exc, "code", "")
    reason = metadata.get("reason") or (
        code
        if code in REASONS
        else {
            "remote_error": "upstream_error",
            "bridge_error": "upstream_error",
            "timeout": "deadline_exceeded",
            "oversized": "resource_limit",
        }.get(code, "invalid_response" if isinstance(exc, ValueError) else "upstream_error")
    )
    return {
        "receivedCount": None,
        "encounteredCount": None,
        "pagesFetched": None,
        "serverTotal": None,
        **metadata,
        "reason": reason,
    }
