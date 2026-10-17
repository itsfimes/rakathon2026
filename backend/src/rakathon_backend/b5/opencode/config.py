from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from rakathon_backend.b5.opencode.validation import (
    AZURE_API_KEY_ENV,
    AZURE_PROVIDER_ID,
    validate_azure_base_url,
    validate_base_url,
    validate_provider_kind,
)


@dataclass(frozen=True, slots=True)
class OpenCodeConfig:
    enabled: bool = False
    blockers: tuple[str, ...] = ()
    binary: str = "opencode"
    expected_version: str = "2.0.31"
    provider_kind: str = "local"
    provider_id: str = ""
    model: str = ""
    base_url: str = ""
    kill_file: str = ""
    startup_timeout: float = 30.0
    request_timeout: float = 180.0
    trust_azure: bool = False
    api_key_present: bool = False

    @property
    def ready(self) -> bool:
        return self.enabled and not self.blockers


def _positive_float(raw: str, default: float) -> float:
    try:
        value = float(raw.strip())
    except (ValueError, AttributeError):
        return default
    if value <= 0:
        return default
    return value


def from_env(env: Mapping[str, str], requested: bool) -> OpenCodeConfig:
    blockers: list[str] = []
    binary = env.get("RAKATHON_AI_BINARY", "").strip() or "opencode"
    expected = env.get("RAKATHON_AI_EXPECTED_VERSION", "").strip() or "2.0.31"
    raw_kind = env.get("RAKATHON_AI_PROVIDER_KIND", "")
    try:
        kind = validate_provider_kind(raw_kind)
    except ValueError as exc:
        blockers.append(f"RAKATHON_AI_PROVIDER_KIND rejected: {exc}")
        kind = "local"
    provider_id = env.get("RAKATHON_AI_PROVIDER", "").strip()
    if kind == "azure" and not provider_id:
        provider_id = AZURE_PROVIDER_ID
    model = env.get("RAKATHON_AI_MODEL", "").strip()
    base_url = env.get("RAKATHON_AI_BASE_URL", "").strip()
    kill_file = env.get("RAKATHON_AI_KILL_FILE", "").strip()
    startup_timeout = _positive_float(env.get("RAKATHON_AI_STARTUP_TIMEOUT", ""), 30.0)
    request_timeout = _positive_float(env.get("RAKATHON_AI_REQUEST_TIMEOUT", ""), 180.0)
    opt_in = env.get("RAKATHON_AI_ENABLE", "").strip() == "1"
    attested = env.get("RAKATHON_AI_OS_EGRESS_ISOLATED", "").strip() == "1"
    trust_azure = env.get("RAKATHON_AI_TRUST_AZURE", "").strip() == "1"
    api_key_present = bool(env.get(AZURE_API_KEY_ENV, "").strip())
    disabled = env.get("AI_DISABLED", "").strip() == "1"
    killed = bool(kill_file) and os.path.exists(kill_file)
    if disabled:
        blockers.append("AI_DISABLED is set")
    if killed:
        blockers.append(f"kill file present at {kill_file}")
    if not opt_in:
        blockers.append("RAKATHON_AI_ENABLE is not 1")
    if kind == "azure":
        if not trust_azure:
            blockers.append("RAKATHON_AI_TRUST_AZURE consent is not 1")
        if not api_key_present:
            blockers.append(f"{AZURE_API_KEY_ENV} is required for azure provider")
    elif not attested:
        blockers.append("RAKATHON_AI_OS_EGRESS_ISOLATED attestation is not 1")
    if not provider_id:
        blockers.append("RAKATHON_AI_PROVIDER is required")
    if not model:
        blockers.append("RAKATHON_AI_MODEL is required")
    if not base_url:
        blockers.append("RAKATHON_AI_BASE_URL is required")
    else:
        try:
            if kind == "azure":
                base_url = validate_azure_base_url(base_url)
            else:
                base_url = validate_base_url(base_url)
        except ValueError as exc:
            blockers.append(f"RAKATHON_AI_BASE_URL rejected: {exc}")
            base_url = ""
    if kind == "azure" and provider_id.lower() == "azure":
        blockers.append("canonical azure provider id strips the api-key header")
        provider_id = ""
    consent_ok = trust_azure if kind == "azure" else attested
    enabled = requested and opt_in and consent_ok and not disabled and not killed
    enabled = bool(enabled and provider_id and model and base_url)
    if kind == "azure":
        enabled = bool(enabled and api_key_present)
    return OpenCodeConfig(
        enabled=enabled,
        blockers=tuple(blockers),
        binary=binary,
        expected_version=expected,
        provider_kind=kind,
        provider_id=provider_id,
        model=model,
        base_url=base_url,
        kill_file=kill_file,
        startup_timeout=startup_timeout,
        request_timeout=request_timeout,
        trust_azure=trust_azure,
        api_key_present=api_key_present,
    )
