from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rakathon_backend.uploads.store import UploadStore

_ALLOWED_PROGRESS_STATUSES = frozenset({"ok", "failed", "tried", "stale", "no-agent"})


def progress_snapshot(out_dir: Path) -> dict[str, Any] | None:
    try:
        raw = (out_dir / "progress.json").read_bytes()
    except OSError:
        return None
    try:
        data: Any = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def drain_progress(store: UploadStore, job_id: str, out_dir: Path) -> None:
    snap = progress_snapshot(out_dir)
    if snap is None:
        return
    events = snap.get("events")
    if isinstance(events, list):
        for entry in events[:16]:
            if not isinstance(entry, dict):
                continue
            code = str(entry.get("code", ""))[:64]
            raw_status = str(entry.get("status", ""))[:32]
            if not raw_status.strip():
                status = "ok"
            else:
                normalized = raw_status.strip().lower()
                status = normalized if normalized in _ALLOWED_PROGRESS_STATUSES else "tried"
            if code:
                store.append_event(job_id, code, status)
    if snap.get("newFormat") is True:
        store.mark_unknown(job_id)
