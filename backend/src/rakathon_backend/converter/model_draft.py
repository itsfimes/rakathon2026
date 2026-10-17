from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MODEL_DRAFT_FILENAME = "model-draft.json"
MODEL_DRAFT_VERSION = 1
MAX_MODEL_OUTPUT_BYTES = 262144
MAX_DRAFT_READ_BYTES = 524288
_DRAFT_KEYS = frozenset({"version", "sourceSha256", "modelOutputText", "candidateText", "model"})
_MODEL_KEYS = frozenset({"providerId", "model"})


def _truncate_bytes(text: str, cap: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= cap:
        return text
    return raw[:cap].decode("utf-8", "ignore")


def _candidate_text(raw: str) -> str:
    try:
        parsed: Any = json.loads(raw)
    except ValueError:
        return _truncate_bytes(raw, MAX_MODEL_OUTPUT_BYTES)
    if isinstance(parsed, dict):
        bundle = parsed.get("bundle")
        if isinstance(bundle, dict):
            try:
                pretty = json.dumps(bundle, indent=2)
            except (ValueError, TypeError):
                return _truncate_bytes(raw, MAX_MODEL_OUTPUT_BYTES)
            return _truncate_bytes(pretty, MAX_MODEL_OUTPUT_BYTES)
    return _truncate_bytes(raw, MAX_MODEL_OUTPUT_BYTES)


def build_model_draft(raw: str, source_sha256: str, provider_id: str, model: str) -> dict[str, Any]:
    return {
        "version": MODEL_DRAFT_VERSION,
        "sourceSha256": source_sha256,
        "modelOutputText": _truncate_bytes(raw, MAX_MODEL_OUTPUT_BYTES),
        "candidateText": _candidate_text(raw),
        "model": {"providerId": provider_id, "model": model},
    }


def is_valid_draft(doc: Any, expected_sha: str) -> bool:
    if not isinstance(doc, dict):
        return False
    if set(doc.keys()) != set(_DRAFT_KEYS):
        return False
    if doc.get("version") != MODEL_DRAFT_VERSION:
        return False
    if doc.get("sourceSha256") != expected_sha:
        return False
    if not isinstance(doc.get("sourceSha256"), str):
        return False
    out = doc.get("modelOutputText")
    cand = doc.get("candidateText")
    if not isinstance(out, str) or not isinstance(cand, str):
        return False
    if not out or not cand:
        return False
    if len(out.encode("utf-8")) > MAX_MODEL_OUTPUT_BYTES:
        return False
    if len(cand.encode("utf-8")) > MAX_MODEL_OUTPUT_BYTES:
        return False
    model = doc.get("model")
    if not isinstance(model, dict):
        return False
    if set(model.keys()) != set(_MODEL_KEYS):
        return False
    provider = model.get("providerId")
    name = model.get("model")
    if not isinstance(provider, str) or not provider:
        return False
    return isinstance(name, str) and bool(name)


def read_draft_bytes(out_dir: Path) -> bytes | None:
    target = out_dir / MODEL_DRAFT_FILENAME
    try:
        if target.is_symlink():
            return None
        size = target.stat().st_size
    except OSError:
        return None
    if size <= 0 or size > MAX_DRAFT_READ_BYTES:
        return None
    try:
        raw = target.read_bytes()
    except OSError:
        return None
    if not raw or len(raw) > MAX_DRAFT_READ_BYTES:
        return None
    return raw
