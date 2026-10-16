from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

from rakathon_backend.b5.gateway import AIAdapter


def _legacy() -> ModuleType:
    return importlib.import_module("rakathon_backend.runtime.legacy_ai")


def ai_config_from_env() -> Any:
    return _legacy().ai_config_from_env()


async def start_ai_adapter(config: Any) -> AIAdapter:
    adapter: AIAdapter = await _legacy().start_ai_adapter(config)
    return adapter


async def probe_version(binary: str, expected: str, timeout: float = 10.0) -> str:
    version: str = await _legacy().probe_version(binary, expected, timeout)
    return version
