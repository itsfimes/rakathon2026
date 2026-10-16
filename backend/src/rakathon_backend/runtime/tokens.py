from __future__ import annotations

import secrets
from typing import Any

FRONTEND_USERS = ("admin", "coordinator", "clinician", "viewer", "watchdog")
SERVICES = ("b1", "b2", "b3", "b4", "b5", "b6")
AI_MODES = ("mock", "opencode")
MIN_WATCHDOG_INTERVAL = 0.1
MAX_WATCHDOG_INTERVAL = 3600.0
KILL_POLL_SECONDS = 1.0


def fresh_tokens() -> dict[str, str]:
    names = list(SERVICES) + [f"frontend:{u}" for u in FRONTEND_USERS]
    return {name: secrets.token_urlsafe(32) for name in names}


class _closer:
    def __init__(self, server: Any) -> None:
        self._server = server

    async def __aenter__(self) -> Any:
        return self._server

    async def __aexit__(self, *args: object) -> None:
        await self._server.close()
