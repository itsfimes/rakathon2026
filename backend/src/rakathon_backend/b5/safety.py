from __future__ import annotations

import os
from pathlib import Path

from rakathon_backend.common.errors import TransportError


def configured_kill_file(env: dict[str, str] | None = None) -> Path | None:
    values = os.environ if env is None else env
    value = values.get("RAKATHON_AI_KILL_FILE", "")
    return Path(value) if value else None


def kill_requested(kill_file: Path | None, *, disabled: str | None = None) -> bool:
    if (os.environ.get("AI_DISABLED", "0") if disabled is None else disabled).strip() == "1":
        return True
    if kill_file is None:
        return False
    try:
        os.lstat(kill_file)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def check_ai_kill(kill_file: Path | None, *, disabled: str | None = None) -> None:
    if kill_requested(kill_file, disabled=disabled):
        raise TransportError(code="killed", message="AI is disabled by the operator")
