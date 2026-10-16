from __future__ import annotations

import tempfile
from pathlib import Path


def short_runtime(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    base = Path("/tmp/opencode")
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="rak", dir=str(base)))
