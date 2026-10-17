from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from collections.abc import Callable
from typing import Any

from rakathon_backend.web.clinical_context import FIELD_SOURCES as FIELD_SOURCES
from rakathon_backend.web.clinical_context import context_for as context_for

ROLES = ("koordinator", "pacient", "lekar", "mdt")
TTL = 300


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


class SnapshotBindings:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._key = secrets.token_bytes(32)
        self.clock = clock

    def token(self, case: dict[str, Any], role: str, issued: int) -> str:
        context_hash = hashlib.sha256(canonical(context_for(case, role))).hexdigest()
        source_hash = hashlib.sha256(
            canonical({"patient": case["patient"], "sections": case["sections"]})
        ).hexdigest()
        payload = [case["patient"]["id"], role, context_hash, source_hash, issued]
        signature = hmac.new(self._key, canonical(payload), hashlib.sha256).hexdigest()
        return f"{issued}.{signature}"

    def previews(self, case: dict[str, Any]) -> dict[str, Any]:
        issued = int(self.clock())
        return {
            role: {
                "context": context_for(case, role),
                "binding": {
                    "caseId": case["patient"]["id"],
                    "token": self.token(case, role, issued),
                },
            }
            for role in ROLES
        }

    def matches(self, case: dict[str, Any], role: str, token: str, context: Any) -> bool:
        if not re.fullmatch(r"[0-9]{1,12}\.[a-f0-9]{64}", token):
            return False
        issued = int(token.split(".", 1)[0])
        if not 0 <= self.clock() - issued <= TTL:
            return False
        return hmac.compare_digest(token, self.token(case, role, issued)) and hmac.compare_digest(
            canonical(context), canonical(context_for(case, role))
        )
