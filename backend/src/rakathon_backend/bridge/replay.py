from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from rakathon_backend.common.errors import ContractError


@dataclass
class ReplayCache:
    max_entries: int = 10000
    ttl_seconds: float = 120.0
    _entries: dict[tuple[str, str], float] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if self.max_entries <= 0 or self.max_entries > 100000:
            raise ValueError("max_entries out of bounds")
        if self.ttl_seconds < 60:
            raise ValueError("ttl must cover token lifetime")

    def _purge_locked(self, now: float) -> None:
        expired = [key for key, exp in self._entries.items() if exp <= now]
        for key in expired:
            del self._entries[key]

    def check_and_store(self, key_id: str, request_id: str) -> None:
        now = time.monotonic()
        identity = (key_id, request_id)
        with self._lock:
            self._purge_locked(now)
            if identity in self._entries:
                raise ContractError(code="replay", message="duplicate request rejected")
            if len(self._entries) >= self.max_entries:
                raise ContractError(code="replay_full", message="replay cache full")
            self._entries[identity] = now + self.ttl_seconds

    def size(self) -> int:
        with self._lock:
            self._purge_locked(time.monotonic())
            return len(self._entries)
