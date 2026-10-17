from __future__ import annotations

import json
from typing import Any

ROLES = ("koordinator", "pacient", "lekar", "mdt")


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
