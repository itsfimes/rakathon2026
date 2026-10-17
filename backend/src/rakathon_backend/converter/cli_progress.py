from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from rakathon_backend.common.fhir import resource_counts

_ATTEMPT_STATUSES = frozenset({"ok", "failed", "tried", "stale", "no-agent"})
_ATTEMPT_CODE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}$")


def _attempt_entry(raw: Any) -> dict[str, str] | None:
    if isinstance(raw, dict):
        code = str(raw.get("code", ""))
        status = str(raw.get("status", ""))
    elif isinstance(raw, str):
        head, sep, tail = raw.rpartition(":")
        if sep:
            code = head
            status = tail
        else:
            code = raw
            status = "tried"
    elif hasattr(raw, "code") and hasattr(raw, "status"):
        code = str(raw.code)
        status = str(raw.status)
    else:
        return None
    code = code.strip()
    status = status.strip().lower()
    if _ATTEMPT_CODE_RE.fullmatch(code) is None:
        return None
    if status not in _ATTEMPT_STATUSES:
        status = "tried"
    return {"code": code, "status": status}


def _attempt_history(info: dict[str, Any]) -> list[dict[str, str]]:
    raw = info.get("attempts", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw[:8]:
        entry = _attempt_entry(item)
        if entry is not None:
            out.append(entry)
    return out


def progress_path(args: argparse.Namespace) -> Path | None:
    try:
        out = Path(str(args.output))
    except (OSError, ValueError):
        return None
    if out.is_symlink():
        return None
    return out / "progress.json"


def write_progress(args: argparse.Namespace, event_code: str, info: dict[str, Any]) -> None:
    target = progress_path(args)
    if target is None:
        return
    try:
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    except OSError:
        return
    payload = {
        "events": [{"code": event_code, "status": "ok"}] + _attempt_history(info),
        "newFormat": bool(info.get("newFormat", False)),
        "recipeReuse": bool(info.get("recipeReuse", False)),
    }
    try:
        target.write_text(json.dumps(payload), encoding="utf-8")
        os.chmod(target, 0o600)
    except OSError:
        return


def report_summary(
    status: str, counts: dict[str, int], model_present: bool, runtime_s: float
) -> None:
    sys.stdout.write(
        json.dumps(
            {
                "status": status,
                "counts": counts,
                "modelPresent": model_present,
                "runtimeS": round(runtime_s, 3),
            }
        )
        + "\n"
    )


def report_stored(result: dict[str, Any], runtime_s: float) -> None:
    counts: dict[str, int] = {}
    bundle = result.get("bundle")
    if isinstance(bundle, dict):
        counts = resource_counts(bundle)
    model = result.get("model")
    present = bool(isinstance(model, dict) and model.get("present") is True)
    report_summary(str(result.get("status")), counts, present, runtime_s)
