from __future__ import annotations

import json
from typing import Any

from rakathon_backend.b1.translation import translate_fixture
from rakathon_backend.common.fhir import is_manual_review, validate_bundle


def mock_translate_bytes(data: bytes, content_type: str) -> dict[str, Any]:
    if content_type == "application/pdf":
        raise ValueError("PDF requires manual review")
    if content_type not in ("text/plain", "application/json"):
        raise ValueError("unsupported content type")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("blob is not valid UTF-8") from exc
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {"patient": {}, "referralReason": ""}
        if text.strip():
            parsed = {"patient": {"id": "", "name": text.strip()[:64]}, "referralReason": ""}
    if not isinstance(parsed, dict):
        raise TypeError("fixture must be a JSON object")
    kind, bundle = translate_fixture(parsed)
    if not validate_bundle(bundle):
        raise ValueError("mock translator produced invalid bundle")
    _ = kind
    _ = is_manual_review(bundle)
    return {"bundle": bundle, "mode": "mock", "synthetic": True}


def mock_complete_bytes(data: bytes, content_type: str) -> dict[str, Any]:
    try:
        prompt = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("prompt is not valid UTF-8") from exc
    _ = content_type
    digest = f"mock-answer for {len(prompt)} chars"
    return {"answer": digest, "mode": "mock", "synthetic": True}
