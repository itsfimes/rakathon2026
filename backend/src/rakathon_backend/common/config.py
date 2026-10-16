from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ConfigError(ValueError):
    message: str = "invalid configuration"


@dataclass(frozen=True, slots=True)
class BackendConfig:
    runtime_dir: Path
    mode: str = "mock"
    service_tokens: dict[str, str] = field(default_factory=dict)

    def token_registry(self) -> dict[str, str]:
        return {token: service for service, token in self.service_tokens.items()}


MIN_TOKEN_LEN = 32


def _parse_tokens(raw: str) -> dict[str, str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"service tokens are not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("service tokens must be a JSON object")
    out: dict[str, str] = {}
    for service, token in data.items():
        if not isinstance(service, str) or not service.strip():
            raise ConfigError("service name must be a nonempty string")
        if not isinstance(token, str) or not token:
            raise ConfigError(f"token for {service} must be a nonempty string")
        out[service.strip()] = token
    return out


def _require_strong(tokens: dict[str, str], mode: str) -> None:
    if mode == "demo":
        return
    for service, token in tokens.items():
        if len(token) < MIN_TOKEN_LEN:
            raise ConfigError(f"token for {service} is too weak for mode {mode!r}")


def load_from_env(env: dict[str, str] | None = None) -> BackendConfig:
    source = dict(os.environ) if env is None else dict(env)
    runtime_dir = Path(source.get("RAKATHON_RUNTIME_DIR", "/tmp/opencode/rakathon")).expanduser()
    mode = source.get("RAKATHON_MODE", "mock").strip() or "mock"
    tokens: dict[str, str] = {}
    raw = source.get("RAKATHON_SERVICE_TOKENS", "").strip()
    if raw:
        tokens = _parse_tokens(raw)
    prefix = "RAKATHON_TOKEN_"
    for key, value in source.items():
        if key.startswith(prefix) and value:
            service = key[len(prefix) :].strip().lower()
            if service:
                tokens[service] = value
    _require_strong(tokens, mode)
    return BackendConfig(runtime_dir=runtime_dir, mode=mode, service_tokens=tokens)


def demo_config(services: tuple[str, ...] = ("b2", "b3", "b4")) -> BackendConfig:
    tokens = {name: secrets.token_urlsafe(32) for name in services}
    return BackendConfig(
        runtime_dir=Path("/tmp/opencode/rakathon-demo"),
        mode="demo",
        service_tokens=tokens,
    )
