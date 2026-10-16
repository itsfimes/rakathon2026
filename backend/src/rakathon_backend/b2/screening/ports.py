from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ScreeningPage:
    rows: list[dict[str, str]]
    offset: int
    limit: int
    truncated: bool


class ScreeningPort(Protocol):
    def query(
        self,
        filters: dict[str, str],
        projection: list[str] | None,
        limit: int,
        offset: int,
    ) -> ScreeningPage: ...

    def describe(self) -> dict[str, Any]: ...
