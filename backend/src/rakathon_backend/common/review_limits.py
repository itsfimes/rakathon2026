from __future__ import annotations

import math
from collections.abc import Mapping

REVIEW_ACTION = "document.approve"
B2_REVIEW_HANDLER_TIMEOUT = 120.0
B4_REVIEW_HANDLER_TIMEOUT = 130.0
B4_REVIEW_PENDING_TIMEOUT = 125.0
B2_REVIEW_CLIENT_TIMEOUT = 125.0
WEB_REVIEW_HTTP_TIMEOUT = 135.0
REVIEW_TIMEOUT_MAX = 600.0
B2_REVIEW_ACTION_TIMEOUTS: dict[str, float] = {REVIEW_ACTION: B2_REVIEW_HANDLER_TIMEOUT}
B4_REVIEW_ACTION_TIMEOUTS: dict[str, float] = {REVIEW_ACTION: B4_REVIEW_HANDLER_TIMEOUT}


def normalize_action_timeouts(raw: Mapping[str, float] | None) -> dict[str, float]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise TypeError("action_timeouts must be a mapping")
    out: dict[str, float] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise TypeError("action timeout key must be a string")
        if not key or key != key.strip():
            raise ValueError("action timeout key must be nonempty without padding")
        if len(key) > 128:
            raise ValueError("action timeout key is too long")
        if any(ch.isspace() for ch in key):
            raise ValueError("action timeout key must not contain whitespace")
        for ch in key:
            if not (ch.isalnum() or ch in ".-_:"):
                raise ValueError("action timeout key has unsafe characters")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("action timeout must be a number")
        numeric = float(value)
        if not math.isfinite(numeric) or numeric <= 0 or numeric > REVIEW_TIMEOUT_MAX:
            raise ValueError("action timeout must be finite positive within bounds")
        if key in out:
            raise ValueError("duplicate action timeout key")
        out[key] = numeric
    return out


def timeout_for(action_timeouts: Mapping[str, float], action: str, default: float) -> float:
    return float(action_timeouts.get(action, default))
