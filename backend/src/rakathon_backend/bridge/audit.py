from __future__ import annotations

import json
import os
import stat
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rakathon_backend.common.errors import ContractError

AuditSink = Callable[[dict[str, Any]], None]


def file_audit_sink(path: Path) -> AuditSink:
    target = Path(path)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
        if mode & 0o077 != 0:
            raise ContractError(code="bad_audit_file", message="audit file must be private")
    except FileNotFoundError:
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    lock = threading.Lock()

    def sink(record: dict[str, Any]) -> None:
        line = (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
        with lock:
            fd = os.open(str(target), os.O_WRONLY | os.O_APPEND)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)

    return sink
