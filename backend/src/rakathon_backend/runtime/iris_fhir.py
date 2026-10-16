from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from rakathon_backend.b2.iris.config import IrisFhirConfig
from rakathon_backend.b2.iris.fhir import DirectFhirAdapter
from rakathon_backend.b2.iris.fhir_only import FhirOnlyStorage
from rakathon_backend.b5.gateway import AIAdapter
from rakathon_backend.common.errors import ContractError
from rakathon_backend.runtime.application import BackendApp

IRIS_FHIR_MODE = "iris-fhir"


def fhir_only_store_from_env(env: dict[str, str] | None = None) -> FhirOnlyStorage:
    source = dict(os.environ) if env is None else dict(env)
    config = IrisFhirConfig.from_env(source, allow_direct_remote=True)
    if not config.trusted_remote:
        raise ContractError(code="not_configured", message="fhir is loopback only")
    adapter = DirectFhirAdapter(config, trusted_remote=True)
    return FhirOnlyStorage(adapter)


def build_iris_fhir_app(
    runtime_dir: Path | str,
    tokens: dict[str, str],
    adapter: AIAdapter | None = None,
    ai_mode: str = "mock",
    kill_file: Path | str | None = None,
    screening: Any | None = None,
) -> BackendApp:
    store = fhir_only_store_from_env()
    return BackendApp(
        Path(runtime_dir),
        dict(tokens),
        store=store,
        mode=IRIS_FHIR_MODE,
        ai_adapter=adapter,
        ai_mode=ai_mode,
        kill_file=kill_file,
        watchdog_interval=None,
        screening=screening,
    )


def describe_iris_fhir_store(store: Any) -> dict[str, str]:
    return {"mode": IRIS_FHIR_MODE, "store": type(store).__name__}
