from __future__ import annotations

import json
import re
import stat
from pathlib import Path
from typing import Any

TRANSCRIPTION_FILENAME = "transcription.json"
TRANSCRIPTION_VERSION = 1
TRANSCRIPTION_METHOD = "opencode-native-files"
MAX_TRANSCRIPTION_READ_BYTES = 1048576
MAX_TRANSCRIPTION_TEXT_BYTES = 262144
MAX_TRANSCRIPTION_PAGES = 2
MAX_TRANSCRIPTION_PAGE_BYTES = 61440
_TRANSCRIPTION_KEYS = frozenset(
    {
        "version",
        "sourceSha256",
        "untrusted",
        "method",
        "modelOutputText",
        "pages",
        "extractSha256",
    }
)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _reject_constant(value: str) -> Any:
    raise ValueError("non-finite constant rejected")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key rejected")
        out[key] = value
    return out


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA_RE.fullmatch(value) is not None


def is_valid_transcription(doc: Any, expected_sha: str) -> bool:
    if not isinstance(doc, dict):
        return False
    if set(doc.keys()) != set(_TRANSCRIPTION_KEYS):
        return False
    if type(doc.get("version")) is not int or doc.get("version") != TRANSCRIPTION_VERSION:
        return False
    source = doc.get("sourceSha256")
    if not _is_sha(source) or source != expected_sha or not _is_sha(expected_sha):
        return False
    if doc.get("untrusted") is not True:
        return False
    if doc.get("method") != TRANSCRIPTION_METHOD:
        return False
    text = doc.get("modelOutputText")
    if not isinstance(text, str) or not text.strip():
        return False
    if len(text.encode("utf-8")) > MAX_TRANSCRIPTION_TEXT_BYTES:
        return False
    pages = doc.get("pages")
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_TRANSCRIPTION_PAGES:
        return False
    total = 0
    for entry in pages:
        if not isinstance(entry, str):
            return False
        total += len(entry.encode("utf-8"))
        if total > MAX_TRANSCRIPTION_PAGE_BYTES:
            return False
    extract = doc.get("extractSha256")
    return not (extract is not None and not _is_sha(extract))


def parse_transcription_bytes(raw: bytes, expected_sha: str) -> dict[str, Any] | None:
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_TRANSCRIPTION_READ_BYTES:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        parsed: Any = json.loads(
            text, object_pairs_hook=_no_duplicates, parse_constant=_reject_constant
        )
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    if not is_valid_transcription(parsed, expected_sha):
        return None
    return parsed


def read_transcription_bytes(out_dir: Path) -> bytes | None:
    target = out_dir / TRANSCRIPTION_FILENAME
    try:
        if target.is_symlink():
            return None
        info = target.stat()
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    if info.st_size <= 0 or info.st_size > MAX_TRANSCRIPTION_READ_BYTES:
        return None
    try:
        raw = target.read_bytes()
    except OSError:
        return None
    if not raw or len(raw) > MAX_TRANSCRIPTION_READ_BYTES:
        return None
    return raw


def load_valid_transcription(out_dir: Path, expected_sha: str) -> bytes | None:
    raw = read_transcription_bytes(out_dir)
    if raw is None:
        return None
    if parse_transcription_bytes(raw, expected_sha) is None:
        return None
    return raw


def is_valid_transcription_bytes(raw: bytes | None, expected_sha: Any) -> bool:
    if raw is None or not isinstance(expected_sha, str):
        return False
    return parse_transcription_bytes(raw, expected_sha) is not None
