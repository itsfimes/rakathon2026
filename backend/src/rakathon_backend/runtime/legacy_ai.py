from __future__ import annotations

import os

from rakathon_backend.b5.opencode.adapter import OpenCodeAdapter
from rakathon_backend.b5.opencode.config import OpenCodeConfig, from_env
from rakathon_backend.b5.opencode.process import probe_version

__all__ = ["probe_version"]


def ai_config_from_env() -> OpenCodeConfig:
    return from_env(dict(os.environ), requested=True)


async def start_ai_adapter(config: OpenCodeConfig) -> OpenCodeAdapter:
    return await OpenCodeAdapter.create(
        config, api_key=os.environ.get("RAKATHON_AI_API_KEY", "").strip()
    )
