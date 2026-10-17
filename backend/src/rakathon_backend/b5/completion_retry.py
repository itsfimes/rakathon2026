from __future__ import annotations

import asyncio
import re
from email.utils import parsedate_to_datetime
from time import monotonic, time

from rakathon_backend.b5.safety import check_ai_kill, configured_kill_file
from rakathon_backend.common.errors import TransportError

MAX_ATTEMPTS = 3
KILL_POLL_SECONDS = 0.1


def rate_limited() -> TransportError:
    return TransportError(code="ai_rate_limited", message="AI provider rate limit reached")


def retry_delay(values: list[str]) -> float:
    if len(values) != 1 or not values[0] or len(values[0]) > 128:
        raise rate_limited()
    value = values[0].strip()
    if re.fullmatch(r"[0-9]+", value):
        return float(value)
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            raise ValueError("Missing timezone")
        return max(0.0, date.timestamp() - time())
    except (ValueError, TypeError, OverflowError):
        raise rate_limited() from None


class CompletionRetry:
    def __init__(self, timeout: float) -> None:
        self.deadline = monotonic() + timeout

    def check(self) -> None:
        check_ai_kill(configured_kill_file())
        if monotonic() >= self.deadline:
            raise TransportError(code="ai_timeout", message="AI provider request timed out")

    async def wait(self, values: list[str], attempt: int) -> None:
        self.check()
        if attempt >= MAX_ATTEMPTS - 1:
            raise rate_limited()
        delay = retry_delay(values)
        now = monotonic()
        if delay >= self.deadline - now:
            raise rate_limited()
        wake = now + delay
        while monotonic() < wake:
            self.check()
            await asyncio.sleep(min(KILL_POLL_SECONDS, wake - monotonic()))
        self.check()
