from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rakathon_backend.uploads.store_io import now_iso, valid_uuid


def read_saved_jobs(index_path: Path) -> dict[str, dict[str, Any]]:
    try:
        raw = index_path.read_bytes()
    except OSError:
        return {}
    try:
        data: Any = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in data.items():
        if valid_uuid(key) and isinstance(value, dict):
            out[key] = dict(value)
    return out


def scan_meta_jobs(store_dir: Path) -> dict[str, dict[str, Any]]:
    try:
        entries = list(store_dir.iterdir())
    except OSError:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not entry.is_dir() or entry.is_symlink():
            continue
        name = entry.name
        if not valid_uuid(name) or name in out:
            continue
        try:
            raw = (entry / "meta.json").read_bytes()
            data: Any = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if isinstance(data, dict) and data.get("id") == name:
            out[name] = dict(data)
    return out


def mark_interrupted_jobs(jobs: dict[str, dict[str, Any]]) -> bool:
    changed = False
    for job in jobs.values():
        if job.get("status") in ("queued", "running"):
            job["status"] = "interrupted"
            events = job.get("events", [])
            if isinstance(events, list):
                events.append({"code": "interrupted_restart", "status": "honest", "at": now_iso()})
            changed = True
    return changed
