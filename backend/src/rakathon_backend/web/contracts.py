from __future__ import annotations

from typing import Any, Protocol

from rakathon_backend.common.contracts import Envelope


class Client(Protocol):
    async def call(self, envelope: Envelope, *, expect_source: str | None = None) -> Envelope: ...
    async def ping(self, service: str) -> Any: ...


class WebError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
