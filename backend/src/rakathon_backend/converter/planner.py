from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

ALLOWED_OPS = frozenset(
    {"charset", "html_strip", "xml_safe", "rtf_text", "hl7_text", "zip_members", "xlsx_bounded"}
)
ALLOWED_CHARSETS = frozenset({"utf-8", "utf-16", "cp1250"})
RECIPE_VERSION = 1
SAMPLE_BYTES = 4096
SAMPLE_TEXT = 2000


def planner_prompt(metadata: dict[str, Any], sample_text: str) -> str:
    brief = {
        "task": "propose ordered decode recipe using ONLY allowed ops",
        "allowedOps": sorted(ALLOWED_OPS),
        "allowedCharsets": sorted(ALLOWED_CHARSETS),
        "detector": metadata,
        "sample": sample_text[:SAMPLE_TEXT],
        "format": "respond ONLY strict JSON "
        '{"version":1,"steps":[{"op":"charset","charset":"utf-8","maxChars":20000}]} '
        "max 5 steps, no code, no shell, no exec, no prose",
    }
    return json.dumps(brief)


def parse_recipe_strict(text: str) -> dict[str, Any]:
    if "```" in text:
        raise ValueError("fenced recipe output")
    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("recipe is not strict JSON") from exc
    if not isinstance(parsed, dict):
        raise TypeError("recipe must be an object")
    if set(parsed.keys()) != {"version", "steps"}:
        raise ValueError("recipe envelope invalid")
    if parsed["version"] != RECIPE_VERSION:
        raise ValueError("recipe version unsupported")
    steps = parsed["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 5:
        raise ValueError("recipe steps must list 1..5 entries")
    clean: list[dict[str, Any]] = []
    for entry in steps:
        if not isinstance(entry, dict) or "op" not in entry:
            raise ValueError("recipe step invalid")
        op = entry["op"]
        if op not in ALLOWED_OPS:
            raise ValueError(f"recipe op {op} is not allowed")
        item: dict[str, Any] = {"op": op}
        if op == "charset":
            charset = entry.get("charset", "utf-8")
            if charset not in ALLOWED_CHARSETS:
                raise ValueError("recipe charset not allowed")
            item["charset"] = charset
            max_chars = entry.get("maxChars", 20000)
            if not isinstance(max_chars, int) or not 64 <= max_chars <= 20000:
                raise ValueError("recipe maxChars out of range")
            item["maxChars"] = max_chars
        elif set(entry.keys()) != {"op"}:
            raise ValueError("recipe step carries unsupported keys")
        clean.append(item)
    return {"version": RECIPE_VERSION, "steps": clean}


def metadata_for(raw: bytes, suffix: str, fingerprint: str, category: str) -> dict[str, Any]:
    head = raw[:SAMPLE_BYTES]
    printable = sum(1 for b in head if 32 <= b <= 126 or b in (9, 10, 13))
    ratio = round(printable / max(1, len(head)), 3)
    return {
        "suffix": suffix,
        "bytes": len(raw),
        "category": category,
        "fingerprint": fingerprint,
        "asciiRatio": ratio,
        "hasNul": b"\x00" in head,
    }


def sample_for_prompt(raw: bytes) -> str:
    for charset in ("utf-8", "utf-16", "cp1250"):
        try:
            text = raw[:SAMPLE_BYTES].decode(charset)
        except (UnicodeDecodeError, ValueError):
            continue
        cleaned = "".join(ch if ch.isprintable() or ch in ("\n", "\t") else " " for ch in text)
        return cleaned[:SAMPLE_TEXT]
    return ""


class RecipeCache:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._items: dict[str, dict[str, Any]] = {}
        if path is not None:
            self._load()

    def _load(self) -> None:
        assert self._path is not None
        try:
            raw = self._path.read_bytes()
        except OSError:
            return
        try:
            data: Any = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(key, str) and isinstance(value, dict):
                    if not key or len(key) > 64:
                        continue
                    try:
                        clean = parse_recipe_strict(json.dumps(value))
                    except (ValueError, TypeError):
                        continue
                    self._items[key] = clean

    def get(self, fingerprint: str) -> dict[str, Any] | None:
        item = self._items.get(fingerprint)
        return dict(item) if item is not None else None

    def put(self, fingerprint: str, recipe: dict[str, Any]) -> None:
        try:
            clean = parse_recipe_strict(json.dumps(recipe))
        except (ValueError, TypeError):
            return
        if not fingerprint or len(fingerprint) > 64:
            return
        self._items[fingerprint] = clean
        self._save()

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            payload = json.dumps(self._items, indent=2).encode("utf-8")
            fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(tmp, 0o600)
                os.replace(tmp, str(self._path))
                try:
                    dir_fd = os.open(str(self._path.parent), os.O_RDONLY | os.O_DIRECTORY)
                except OSError:
                    dir_fd = -1
                if dir_fd >= 0:
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        except OSError:
            return

    def fingerprint_material(self, fingerprint: str) -> str:
        return hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
