from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from rakathon_backend.common.ai_limits import (
    AI_EDGE_TIMEOUT,
    AI_FRONTEND_TIMEOUT,
    AI_GATEWAY_TIMEOUT,
    AI_IPC_TIMEOUT,
    AI_REQUEST_TIMEOUT,
)
from rakathon_backend.common.fhir import is_manual_review, validate_bundle

__all__ = [
    "AI_EDGE_TIMEOUT",
    "AI_FRONTEND_TIMEOUT",
    "AI_GATEWAY_TIMEOUT",
    "AI_IPC_TIMEOUT",
    "AI_REQUEST_TIMEOUT",
]

EXPECTED_VERSION = "2.0.31"
API_USERNAME = "opencode"
MAX_INPUT_BYTES = 65536
MAX_RESPONSE_BYTES = 262144
MAX_PROMPT_CHARS = 65536
VERSION_PROBE_TIMEOUT = 10.0
STARTUP_TIMEOUT = 30.0
REQUEST_TIMEOUT = 180.0
CONNECT_TIMEOUT = 5.0
HEALTH_POLL_INTERVAL = 0.2
PROCESS_KILL_TIMEOUT = 5.0
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
AZURE_BASE_URL = "https://apim-rakathon-q7146n.azure-api.net/openai/v1"
AZURE_PROVIDER_ID = "rakathon-azure"
AZURE_API_KEY_ENV = "RAKATHON_AI_API_KEY"
AZURE_API_KEY_HEADER = "api-key"
AZURE_API_KEY_REF = "{env:RAKATHON_AI_API_KEY}"
PROVIDER_PACKAGE = "@ai-sdk/openai-compatible"
DENY_ALL_RULE = {"action": "*", "resource": "*", "effect": "deny"}

_VERSION_RE = re.compile(r"^opencode v(\d+\.\d+\.\d+)\s*$")
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def validate_base_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("provider base URL is required")
    try:
        parts = urlsplit(value)
    except ValueError as exc:
        raise ValueError("provider base URL is malformed") from exc
    if parts.scheme != "http":
        raise ValueError("provider base URL must use http loopback")
    host = (parts.hostname or "").strip().lower()
    if host not in LOOPBACK_HOSTS:
        raise ValueError("provider base URL must use a literal loopback address")
    if parts.port is None:
        raise ValueError("provider base URL must include an explicit port")
    if parts.username or parts.password:
        raise ValueError("provider base URL must not embed credentials")
    if parts.query or parts.fragment:
        raise ValueError("provider base URL must not carry query or fragment")
    normalized_host = f"[{host}]" if ":" in host else host
    normalized = f"http://{normalized_host}:{parts.port}"
    path = parts.path
    if path and path != "/":
        normalized += path
    return normalized


def validate_azure_base_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("azure provider base URL is required")
    candidate = value[:-1] if value.endswith("/") and len(value) > 1 else value
    if candidate != AZURE_BASE_URL:
        raise ValueError("azure provider base URL is not the trusted endpoint")
    return AZURE_BASE_URL


def validate_provider_kind(raw: str) -> str:
    kind = raw.strip().lower() or "local"
    if kind not in ("local", "azure"):
        raise ValueError("provider kind must be local or azure")
    return kind


def parse_version_output(text: str, expected: str = EXPECTED_VERSION) -> str:
    match = _VERSION_RE.match(text.strip())
    if match is None:
        raise ValueError("opencode version output is unrecognized")
    version = match.group(1)
    if version != expected:
        raise ValueError(f"opencode version {version} does not match required {expected}")
    return version


def validate_session_id(raw: str) -> str:
    if not isinstance(raw, str) or _SESSION_ID_RE.match(raw) is None:
        raise ValueError("session id is not a safe path segment")
    return raw


def parse_session_id(body: Any) -> str:
    session_id: Any = None
    if isinstance(body, dict):
        session_id = body.get("id")
        if session_id is None and isinstance(body.get("data"), dict):
            session_id = body["data"].get("id")
    if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 128:
        raise ValueError("session creation response carries no usable id")
    return session_id.strip()


def parse_generate_text(body: Any) -> str:
    text: Any = None
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        text = body["data"].get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("generate response carries no usable text")
    if len(text) > MAX_RESPONSE_BYTES:
        raise ValueError("generate response exceeds size cap")
    return text


def parse_model_output(text: str) -> dict[str, Any]:
    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("model output is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise TypeError("model output must be a JSON object")
    if "bundle" in parsed:
        bundle = parsed["bundle"]
        if not isinstance(bundle, dict) or not validate_bundle(bundle):
            raise ValueError("model bundle failed FHIR validation")
        _ = is_manual_review(bundle)
        return {"bundle": bundle}
    outcome = parsed.get("outcome")
    if (
        isinstance(outcome, dict)
        and parsed.get("manualReview") is True
        and outcome.get("resourceType") == "OperationOutcome"
        and isinstance(outcome.get("issue"), list)
        and bool(outcome["issue"])
    ):
        return {"bundle": outcome}
    raise ValueError("model output matches neither bundle nor reviewed outcome shape")


def build_config_content(
    provider_id: str,
    model: str,
    base_url: str,
    *,
    provider_kind: str = "local",
) -> str:
    kind = validate_provider_kind(provider_kind)
    if not provider_id.strip() or len(provider_id) > 64:
        raise ValueError("provider id is required")
    if not model.strip() or len(model) > 128:
        raise ValueError("model name is required")
    pid = provider_id.strip()
    name = model.strip()
    if kind == "azure":
        if pid.lower() == "azure":
            raise ValueError("canonical azure provider id strips the api-key header")
        normalized = validate_azure_base_url(base_url)
        options: dict[str, Any] = {
            "baseURL": normalized,
            "headers": {AZURE_API_KEY_HEADER: AZURE_API_KEY_REF},
        }
    else:
        normalized = validate_base_url(base_url)
        options = {"baseURL": normalized}
    content: dict[str, Any] = {
        "provider": {
            pid: {
                "npm": PROVIDER_PACKAGE,
                "name": pid,
                "options": options,
                "models": {name: {"name": name}},
            }
        },
        "permission": "deny",
        "policies": [
            {"action": "provider.use", "resource": "*", "effect": "deny"},
            {"action": "provider.use", "resource": pid, "effect": "allow"},
            {"action": "tool.use", "resource": "*", "effect": "deny"},
            {"action": "integration.use", "resource": "mcp:*", "effect": "deny"},
            {"action": "integration.use", "resource": "plugin:*", "effect": "deny"},
        ],
        "model": f"{pid}/{name}",
    }
    return json.dumps(content)


def build_translate_prompt(raw_text: str) -> str:
    if len(raw_text) > MAX_PROMPT_CHARS:
        raise ValueError("translate input exceeds prompt cap")
    return (
        "Translate the following clinical or administrative document text into FHIR R4 JSON. "
        "Respond with ONLY a JSON object, no prose, no markdown fences. "
        'Either {"bundle": <FHIR R4 transaction Bundle>} when the text supports '
        "at least one faithful resource, or "
        '{"outcome": <FHIR OperationOutcome describing the gap>, '
        '"manualReview": true} when data is missing or the document is administrative. "'
        "Allowed resource types only: Patient, ServiceRequest, Observation, "
        "DiagnosticReport, DocumentReference, Condition, Procedure, and Provenance "
        "only when the text genuinely supports it. "
        "Administrative templates map to a single DocumentReference, never to a "
        "forced Patient or ServiceRequest. "
        "Never invent patient identifiers, names, dates of birth, ages, referrals, "
        "or clinical facts. Patient.name is optional: omit it when absent. "
        "Never compute a birth date from an age and never invent identifiers or "
        "screening referrals. "
        "Use only valid known status values (or unknown); never guess a clinical "
        "status. Every entry needs method plus path plus id consistency, unique "
        "ids and references, closed references inside the Bundle, and no "
        "executable or arbitrary URLs. "
        "Document text:\n" + raw_text
    )


def build_complete_prompt(raw_text: str) -> str:
    if len(raw_text) > MAX_PROMPT_CHARS:
        raise ValueError("complete input exceeds prompt cap")
    return raw_text
