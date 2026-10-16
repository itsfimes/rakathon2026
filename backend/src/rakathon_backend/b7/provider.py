from __future__ import annotations

import re
import threading

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError

from rakathon_backend.common.errors import ContractError

_HASH_RE = re.compile(r"^\$argon2id\$v=\d+\$m=(\d+),t=(\d+),p=(\d+)\$")
MAX_MEMORY = 262144
MAX_TIME = 10
MAX_PARALLELISM = 4


def check_params_clamped(stored: str) -> None:
    match = _HASH_RE.match(stored)
    if match is None:
        raise ContractError(code="bad_payload", message="stored hash invalid")
    memory = int(match.group(1))
    cost = int(match.group(2))
    parallel = int(match.group(3))
    if memory < 1 or memory > MAX_MEMORY or cost < 1 or cost > MAX_TIME:
        raise ContractError(code="bad_payload", message="stored hash invalid")
    if parallel < 1 or parallel > MAX_PARALLELISM:
        raise ContractError(code="bad_payload", message="stored hash invalid")


class LocalPasswordProvider:
    def __init__(
        self,
        time_cost: int = 3,
        memory_cost: int = 65536,
        parallelism: int = 1,
        max_concurrent: int = 4,
    ) -> None:
        self._hasher = PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=32,
            salt_len=16,
        )
        self._gate = threading.BoundedSemaphore(max_concurrent)
        self._dummy_hash = self._hasher.hash("dummy-reserve-0123456789abcdef")

    @property
    def hasher(self) -> PasswordHasher:
        return self._hasher

    def hash_password(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, stored: str, password: str) -> bool:
        check_params_clamped(stored)
        try:
            return self._hasher.verify(stored, password)
        except (VerifyMismatchError, InvalidHash):
            return False

    def dummy_verify(self) -> None:
        try:
            self._hasher.verify(self._dummy_hash, "dummy-wrong-0123456789abcdef")
        except (VerifyMismatchError, InvalidHash):
            return
        return

    def try_acquire(self) -> bool:
        return self._gate.acquire(blocking=False)

    def release(self) -> None:
        self._gate.release()

    def needs_rehash(self, stored: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(stored)
        except (InvalidHash, AttributeError):
            return False
