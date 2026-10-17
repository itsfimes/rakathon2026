from __future__ import annotations

import json
from threading import Event
from typing import Any

from rakathon_backend.web.contracts import WebError


def context_too_large() -> WebError:
    return WebError(413, "context_too_large", "Patient context exceeds the assistant size limit")


class ByteBudget:
    def __init__(self, limit: int, cancelled: Event | None = None) -> None:
        self.remaining = limit
        self.cancelled = cancelled

    def check(self) -> None:
        if self.cancelled is not None and self.cancelled.is_set():
            raise WebError(503, "unavailable", "Patient context collection cancelled")
        if self.remaining < 0:
            raise context_too_large()

    def consume(self, size: int) -> None:
        self.remaining -= size
        self.check()

    def charge(self, value: Any) -> None:
        encoder = json.JSONEncoder(ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        for part in encoder.iterencode(value):
            self.consume(len(part.encode("utf-8")))
