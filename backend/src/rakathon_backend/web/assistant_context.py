from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from collections.abc import Callable
from typing import Any

ROLES = ("koordinator", "pacient", "lekar", "mdt")
FIELD_SOURCES = {
    "record.coverage": "record-coverage",
    "record.reportsSummary": "record-report-metadata",
}
TTL = 300


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _label(concept: Any) -> str | None:
    if not isinstance(concept, dict):
        return None
    text = concept.get("text")
    if isinstance(text, str):
        return text
    for coding in concept.get("coding", []):
        display = coding.get("display") if isinstance(coding, dict) else None
        if isinstance(display, str):
            return display
    return None


def _safe_title(title: Any, case: dict[str, Any]) -> bool:
    if not isinstance(title, str) or not title.strip() or len(title) > 160:
        return False
    if re.search(
        r"[<>]|https?://|\b\d{6,}\b|(?:Patient|Observation|DiagnosticReport|DocumentReference)/",
        title,
    ):
        return False
    patient = case["patient"]
    private = [patient["id"]]
    for name in patient.get("name", []):
        private.extend([name.get("text", ""), name.get("family", ""), *name.get("given", [])])
    private.extend(item.get("value", "") for item in patient.get("telecom", []))
    for item in case["sections"]["conditions"]["items"]:
        label = _label(item.get("code"))
        if label:
            private.append(label)
    return not any(len(value) >= 3 and value.casefold() in title.casefold() for value in private)


def _date(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(
        r"[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2}(?:T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2}))?)?)?",
        value,
    ):
        return value
    return None


def _status(value: Any) -> str | None:
    return (
        value
        if isinstance(value, str)
        and value
        in {
            "registered",
            "partial",
            "preliminary",
            "final",
            "amended",
            "corrected",
            "appended",
            "cancelled",
            "entered-in-error",
            "unknown",
            "current",
            "superseded",
        }
        else None
    )


def context_for(case: dict[str, Any], role: str) -> dict[str, Any]:
    sections = case["sections"]
    labels = {
        "conditions": "Diagnózy",
        "observations": "Pozorování",
        "diagnosticReports": "Zprávy",
        "documents": "Dokumenty",
    }
    coverage = "; ".join(
        f"{label}: {'načteno' if sections[key]['status'] == 'complete' else 'nedostupné'}"
        for key, label in labels.items()
    )
    fields = [{"key": "record.coverage", "source": "record-coverage", "value": coverage}]
    reports = []
    if role != "koordinator":
        for item in sections["diagnosticReports"]["items"]:
            title = _label(item.get("code"))
            if _safe_title(title, case):
                parts = [
                    title,
                    _date(item.get("issued")) or _date(item.get("effectiveDateTime")),
                    _status(item.get("status")),
                ]
                reports.append(" · ".join(part for part in parts if isinstance(part, str)))
        for item in sections["documents"]["items"]:
            for content in item.get("content", []):
                attachment = content.get("attachment", {})
                title = attachment.get("title")
                if _safe_title(title, case):
                    parts = [
                        title,
                        _date(attachment.get("creation")) or _date(item.get("date")),
                        _status(item.get("status")),
                    ]
                    reports.append(" · ".join(part for part in parts if isinstance(part, str)))
        for value in reports[:3]:
            if len(value) <= 320:
                fields.append(
                    {
                        "key": "record.reportsSummary",
                        "source": "record-report-metadata",
                        "value": value,
                    }
                )
    return {"role": role, "fields": fields}


class SnapshotBindings:
    def __init__(self, clock: Callable[[], float] = time.time, *, key: bytes | None = None) -> None:
        if key is not None:
            if not isinstance(key, (bytes, bytearray)) or len(bytes(key)) != 32:
                raise ValueError("binding key must be 32 bytes")
            self._key = bytes(key)
        else:
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
