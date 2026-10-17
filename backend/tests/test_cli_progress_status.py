from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rakathon_backend.converter.cli_progress import write_progress
from rakathon_backend.uploads.worker_progress import drain_progress


class _StubStore:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.unknown_marks = 0

    def append_event(self, job_id: str, code: str, status: str) -> None:
        _ = job_id
        self.events.append((code, status))

    def mark_unknown(self, job_id: str) -> None:
        _ = job_id
        self.unknown_marks += 1


def _args(out_dir: Path) -> argparse.Namespace:
    return argparse.Namespace(output=str(out_dir))


def _events(out_dir: Path) -> list[dict[str, Any]]:
    raw = (out_dir / "progress.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    events = data["events"]
    assert isinstance(events, list)
    return [item for item in events if isinstance(item, dict)]


def test_failure_status_preserved_not_forced_ok(tmp_path: Path) -> None:
    attempts = [
        "charset_utf8:ok",
        "planner_recipe:failed",
        "planner_fallback:tried",
        "cache_reuse:stale",
        "planner_fallback:no-agent",
    ]
    write_progress(_args(tmp_path), "decode_done", {"attempts": attempts})
    events = _events(tmp_path)
    assert events[0] == {"code": "decode_done", "status": "ok"}
    assert [(item["code"], item["status"]) for item in events[1:]] == [
        ("charset_utf8", "ok"),
        ("planner_recipe", "failed"),
        ("planner_fallback", "tried"),
        ("cache_reuse", "stale"),
        ("planner_fallback", "no-agent"),
    ]


def test_unknown_status_neutralized_and_bad_code_dropped(tmp_path: Path) -> None:
    write_progress(
        _args(tmp_path),
        "planner_start",
        {"attempts": ["mystery:bogus", "barecode", "has space:ok", "good:ok"]},
    )
    events = _events(tmp_path)
    assert events[0] == {"code": "planner_start", "status": "ok"}
    assert [(item["code"], item["status"]) for item in events[1:]] == [
        ("mystery", "tried"),
        ("barecode", "tried"),
        ("good", "ok"),
    ]


def test_attempt_history_bounded_to_eight(tmp_path: Path) -> None:
    attempts = ["charset_utf8:ok"] * 3 + ["planner_recipe:failed"] * 9
    write_progress(_args(tmp_path), "decode_done", {"attempts": attempts})
    events = _events(tmp_path)
    assert len(events) == 9
    assert events[1]["status"] == "ok"
    assert events[-1] == {"code": "planner_recipe", "status": "failed"}


def test_drain_propagates_real_status_and_bounds_unknown(tmp_path: Path) -> None:
    write_progress(
        _args(tmp_path),
        "decode_done",
        {"newFormat": True, "attempts": ["planner_recipe:failed", "weird:bogus"]},
    )
    store: Any = _StubStore()
    drain_progress(store, "job-1", tmp_path)
    assert ("decode_done", "ok") in store.events
    assert ("planner_recipe", "failed") in store.events
    assert ("weird", "tried") in store.events
    assert all(status != "bogus" for _, status in store.events)
    assert store.unknown_marks == 1


def test_drain_missing_status_defaults_ok(tmp_path: Path) -> None:
    (tmp_path / "progress.json").write_text(
        json.dumps({"events": [{"code": "planner_start"}]}), encoding="utf-8"
    )
    store: Any = _StubStore()
    drain_progress(store, "job-1", tmp_path)
    assert ("planner_start", "ok") in store.events
