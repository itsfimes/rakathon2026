from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rakathon_backend.common.ipc import UnixJsonClient
from rakathon_backend.common.rpc import socket_for

if TYPE_CHECKING:
    from rakathon_backend.runtime.application import BackendApp

PROBE_SOURCES = {
    "b6": "b4",
    "b2": "b4",
    "b5": "b1",
    "b1": "b4",
    "b4": "frontend:admin",
    "b3": "b3",
}


async def health_all(app: BackendApp, services: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in services:
        src = PROBE_SOURCES.get(name, "b4")
        token = app.tokens.get(src, next(iter(app.tokens.values())))
        client = UnixJsonClient(socket_for(Path(app.runtime_dir), name), token=token, source=src)
        out[name] = (await client.ping(name)).value
    return out
