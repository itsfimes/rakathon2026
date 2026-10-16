from __future__ import annotations

import stat
from collections.abc import Mapping
from pathlib import Path

from rakathon_backend.common.contracts import Health

_PRIORITY = {Health.DOWN: 2, Health.DEGRADED: 1, Health.HEALTHY: 0}


def socket_present(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    if path.is_symlink():
        return False
    return stat.S_ISSOCK(info.st_mode)


def summarize(results: Mapping[str, Health]) -> Health:
    worst = Health.HEALTHY
    for value in results.values():
        if _PRIORITY[value] > _PRIORITY[worst]:
            worst = value
    return worst
