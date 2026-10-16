from __future__ import annotations

import os
import re
import stat
from pathlib import Path

KNOWN_ENV_KEYS = frozenset(
    {
        "RAKATHON_AI_ENABLE",
        "RAKATHON_AI_OS_EGRESS_ISOLATED",
        "RAKATHON_AI_TRUST_AZURE",
        "RAKATHON_AI_PROVIDER_KIND",
        "RAKATHON_AI_PROVIDER",
        "RAKATHON_AI_MODEL",
        "RAKATHON_AI_BASE_URL",
        "RAKATHON_AI_BINARY",
        "RAKATHON_AI_EXPECTED_VERSION",
        "RAKATHON_AI_STARTUP_TIMEOUT",
        "RAKATHON_AI_REQUEST_TIMEOUT",
        "RAKATHON_AI_API_KEY",
        "RAKATHON_AI_KILL_FILE",
        "AI_DISABLED",
        "RAKATHON_IRIS_FHIR_BASE_URL",
        "RAKATHON_IRIS_FHIR_USER",
        "RAKATHON_IRIS_FHIR_PASSWORD",
        "RAKATHON_IRIS_FHIR_VERIFY_TLS",
        "RAKATHON_IRIS_FHIR_ALLOW_DIRECT",
    }
)

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check_private_file(path: Path) -> None:
    if path.is_symlink():
        raise PermissionError(f"env file must not be a symlink: {path}")
    try:
        info = path.stat()
    except OSError as exc:
        raise OSError(f"env file is not readable: {path}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise PermissionError(f"env file must be a regular file: {path}")
    if info.st_uid != os.getuid():
        raise PermissionError(f"env file must be owned by the current user: {path}")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise PermissionError(f"env file must have mode 0600: {path}")


def _parse_line(line: str, lineno: int, path: Path) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if "=" not in text:
        raise ValueError(f"env file line {lineno} has no KEY=VALUE assignment: {path}")
    key, _, value = text.partition("=")
    key = key.strip()
    value = value.strip()
    if not _KEY_RE.match(key):
        raise ValueError(f"env file line {lineno} has an invalid key: {path}")
    if key not in KNOWN_ENV_KEYS:
        raise ValueError(f"env file line {lineno} names an unknown key: {key}")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return (key, value)


def parse_env_file(path: str | Path) -> dict[str, str]:
    target = Path(path)
    _check_private_file(target)
    try:
        raw = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"env file is not readable UTF-8 text: {target}") from exc
    parsed: dict[str, str] = {}
    for lineno, line in enumerate(raw.splitlines(), start=1):
        item = _parse_line(line, lineno, target)
        if item is not None:
            parsed[item[0]] = item[1]
    return parsed


def apply_env_file(path: str | Path) -> list[str]:
    parsed = parse_env_file(path)
    filled: list[str] = []
    for key in sorted(parsed):
        if key not in os.environ:
            os.environ[key] = parsed[key]
            filled.append(key)
    return filled
