from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.common.errors import ContractError
from rakathon_backend.converter.planner import RecipeCache
from rakathon_backend.uploads.crypto import generate_key_file
from rakathon_backend.uploads.http import UploadRoutes
from rakathon_backend.uploads.store import UploadStore, sanitize_filename
from rakathon_backend.uploads.worker import UploadWorker

LAUNCHER_SRC = Path(__file__).parent.parent / "scripts" / "run_converter.py"


def _store(tmp_path: Path) -> UploadStore:
    d = tmp_path / "s"
    d.mkdir(mode=0o700)
    keys = generate_key_file(d / "store.key")
    return UploadStore(d, keys)


def _review_runner(src: Path, out: Path, allow: bool) -> int:
    _ = allow
    try:
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
    except OSError:
        sha = ""
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(
        json.dumps(
            {
                "status": "manual-review",
                "bundle": None,
                "issues": [{"code": "unknown_no_extract", "message": "no decoder"}],
                "evidence": [],
                "needsReview": True,
                "writeEligible": False,
                "persistence": "not-written",
                "model": {"providerId": "p", "model": "m", "present": False},
                "source": {"sha256": sha},
                "adaptive": {
                    "newFormat": True,
                    "recipeReuse": False,
                    "plannerMode": "fallback",
                    "attempts": ["planner_fallback:no-agent"],
                    "fingerprint": "fp",
                },
            }
        )
    )
    (out / "provenance.json").write_text(
        json.dumps({"sourceSha256": sha, "adaptive": {"plannerMode": "fallback"}})
    )
    return 0


def test_suffix_preserved_pdf(tmp_path: Path) -> None:
    store = _store(tmp_path)
    seen: dict[str, str] = {}

    def runner(src: Path, out: Path, allow: bool) -> int:
        seen["suffix"] = src.suffix
        return _review_runner(src, out, allow)

    worker = UploadWorker(store, runner=runner)
    body = b"%PDF-1.4 synthetic pdf body with words"
    job = store.enqueue("u1", "SYN-1", "report.pdf", body)
    worker._convert(job["id"])
    assert seen.get("suffix") == ".pdf"
    back = store.get(job["id"])
    assert back is not None and back["status"] == "manual-review"


def test_no_local_fallback_without_docker(tmp_path: Path, monkeypatch: Any) -> None:
    store = _store(tmp_path)
    worker = UploadWorker(store, runner=None)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    job = store.enqueue("u1", "SYN-1", "a.hl7", b"readable synthetic ward note with words")
    worker._convert(job["id"])
    back = store.get(job["id"])
    assert back is not None and back["status"] == "failed"
    assert store.read_original(job["id"]) == b"readable synthetic ward note with words"


def test_early_unknown_event(tmp_path: Path) -> None:
    store = _store(tmp_path)
    worker = UploadWorker(store, runner=_review_runner)
    job = store.enqueue("u1", "SYN-1", "note.weirdfmt", b"readable synthetic ward note words here")
    worker._convert(job["id"])
    back = store.get(job["id"])
    assert back is not None and back["newFormat"] is True
    codes = [e.get("code") for e in back.get("events", []) if isinstance(e, dict)]
    assert "new_format_detected" in codes


def test_exit_mismatch_cannot_complete(tmp_path: Path) -> None:
    store = _store(tmp_path)

    def bad_runner(src: Path, out: Path, allow: bool) -> int:
        _ = allow
        try:
            sha = hashlib.sha256(src.read_bytes()).hexdigest()
        except OSError:
            sha = ""
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").write_text(
            json.dumps(
                {
                    "status": "complete",
                    "bundle": None,
                    "issues": [],
                    "evidence": [],
                    "needsReview": True,
                    "writeEligible": False,
                    "persistence": "not-written",
                    "model": {"providerId": "p", "model": "m", "present": True},
                    "source": {"sha256": sha},
                    "adaptive": {
                        "newFormat": False,
                        "recipeReuse": False,
                        "plannerMode": "none",
                        "attempts": [],
                        "fingerprint": "",
                    },
                }
            )
        )
        (out / "provenance.json").write_text(json.dumps({"sourceSha256": sha}))
        return 2

    worker = UploadWorker(store, runner=bad_runner)
    job = store.enqueue("u1", "SYN-1", "a.hl7", b"readable synthetic ward note words here")
    worker._convert(job["id"])
    back = store.get(job["id"])
    assert back is not None and back["status"] == "failed"


def test_two_jobs_first_failure_next_completes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    calls = {"n": 0}

    def runner(src: Path, out: Path, allow: bool) -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return _review_runner(src, out, allow)

    worker = UploadWorker(store, runner=runner)
    j1 = store.enqueue("u1", "SYN-1", "a.hl7", b"readable synthetic ward note alpha words")
    j2 = store.enqueue("u1", "SYN-1", "b.hl7", b"readable synthetic ward note beta words")
    worker._convert(j1["id"])
    worker._convert(j2["id"])
    b1 = store.get(j1["id"])
    b2 = store.get(j2["id"])
    assert b1 is not None and b1["status"] == "failed"
    assert b2 is not None and b2["status"] == "manual-review"


def test_queue_caps_exact(tmp_path: Path) -> None:
    store = _store(tmp_path)

    for i in range(2):
        store.enqueue("u1", "SYN-1", f"f{i}.hl7", b"words number %d readable here" % i)
    with pytest.raises(ContractError):
        store.enqueue("u1", "SYN-1", "extra.hl7", b"overflow words readable here")
    store.enqueue("u2", "SYN-1", "a.hl7", b"other user words readable here")
    store.enqueue("u3", "SYN-1", "b.hl7", b"third user words readable here")
    with pytest.raises(ContractError):
        store.enqueue("u4", "SYN-1", "c.hl7", b"global overflow words here")


def test_download_revoked_case_denied(tmp_path: Path) -> None:
    store = _store(tmp_path)
    worker = UploadWorker(store, runner=_review_runner)
    routes = UploadRoutes(
        store, worker, authorize=lambda u, a: True, case_access=lambda u, c: False
    )
    out = routes.handle(
        "u1",
        "clinician",
        "POST",
        "/api/v1/cases/SYN-1/uploads",
        {"content-type": "application/octet-stream", "x-upload-name": "a.hl7"},
        b"readable words here",
    )
    assert out is not None
    status, _, _ = out
    assert status in (404, 503)
    job = store.enqueue("u1", "SYN-1", "a.hl7", b"readable words here for download")
    got = routes.handle("u1", "clinician", "GET", f"/api/v1/uploads/{job['id']}", {}, None)
    assert got is not None
    status, _, _ = got
    assert status == 404
    got2 = routes.handle(
        "u1", "clinician", "GET", f"/api/v1/uploads/{job['id']}/original", {}, None
    )
    assert got2 is not None
    status, _, _ = got2
    assert status == 404


def test_filename_controls_rejected() -> None:
    with pytest.raises(ContractError):
        sanitize_filename("bad\x01name.hl7")
    with pytest.raises(ContractError):
        sanitize_filename("bad\x7fname.hl7")
    assert sanitize_filename("klinika-žluťoučký.hl7") == "klinika-žluťoučký.hl7"


def test_recipe_cache_no_phi(tmp_path: Path) -> None:
    cache_file = tmp_path / "recipes.json"
    cache = RecipeCache(cache_file)
    cache.put(
        "fp1", {"version": 1, "steps": [{"op": "charset", "charset": "utf-8", "maxChars": 5000}]}
    )
    stored = cache_file.read_text(encoding="utf-8")
    assert "SYN" not in stored and ".hl7" not in stored
    assert cache.get("fp1") is not None


def test_launcher_recipe_cache_mount() -> None:
    text = LAUNCHER_SRC.read_text(encoding="utf-8")
    assert "--recipe-cache" in text
    assert ":ro" in text
    assert "RAKATHON_RECIPE_CACHE_FILE" in text
    assert "killpg" in text


def test_progress_poll_appends(tmp_path: Path) -> None:
    store = _store(tmp_path)

    def prog_runner(src: Path, out: Path, allow: bool) -> int:
        _ = (src, allow)
        out.mkdir(parents=True, exist_ok=True)
        (out / "progress.json").write_text(
            json.dumps({"events": [{"code": "planner_start", "status": "ok"}], "newFormat": True})
        )
        return _review_runner(src, out, allow)

    worker = UploadWorker(store, runner=prog_runner)
    job = store.enqueue("u1", "SYN-1", "x.weird", b"readable synthetic ward note words here")
    worker.submit(job["id"])
    deadline = time.time() + 5
    while time.time() < deadline:
        back = store.get(job["id"])
        if back is not None and back.get("status") not in ("queued", "running"):
            break
        time.sleep(0.05)
    back = store.get(job["id"])
    assert back is not None and back["status"] == "manual-review"
    worker.close()
