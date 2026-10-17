from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from rakathon_backend.uploads.crypto import generate_key_file
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.uploads.worker import UploadWorker


def _store(tmp_path: Path) -> tuple[UploadStore, Path, Any]:
    d = tmp_path / "s"
    d.mkdir(mode=0o700)
    keys = generate_key_file(d / "store.key")
    return (UploadStore(d, keys), d, keys)


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


def _wait_for(pred: Any, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return
        time.sleep(0.02)
    assert pred()


def test_cancelled_submit_never_steals_sibling(tmp_path: Path) -> None:
    store, _, _ = _store(tmp_path)
    executed: list[str] = []

    def runner(src: Path, out: Path, allow: bool) -> int:
        executed.append(src.read_bytes()[:8].hex())
        return _review_runner(src, out, allow)

    worker = UploadWorker(store, runner=runner)
    try:
        body_a = b"cancelled alpha payload SYN-A words here"
        body_b = b"legit beta payload SYN-B words here"
        job_a = store.enqueue("u1", "SYN-1", "a.hl7", body_a)
        job_b = store.enqueue("u1", "SYN-1", "b.hl7", body_b)
        assert store.cancel(job_a["id"], "u1") is True
        worker.submit(job_a["id"])
        _wait_for(lambda: len(worker._pending) == 0)
        assert executed == []
        back_b = store.get(job_b["id"])
        assert back_b is not None and back_b["status"] == "queued"
        back_a = store.get(job_a["id"])
        assert back_a is not None and back_a["status"] == "cancelled"
        worker.submit(job_b["id"])
        _wait_for(lambda: (store.get(job_b["id"]) or {}).get("status") not in ("queued", "running"))
        done_b = store.get(job_b["id"])
        assert done_b is not None and done_b["status"] == "manual-review"
        cancelled_a = store.get(job_a["id"])
        assert cancelled_a is not None and cancelled_a["status"] == "cancelled"
        assert len(executed) == 1
    finally:
        worker.close()


def test_claim_exception_fails_requested_without_steal(tmp_path: Path, monkeypatch: Any) -> None:
    store, _, _ = _store(tmp_path)
    executed: list[Path] = []

    def runner(src: Path, out: Path, allow: bool) -> int:
        executed.append(src)
        return _review_runner(src, out, allow)

    worker = UploadWorker(store, runner=runner)
    try:
        job_a = store.enqueue("u1", "SYN-1", "a.hl7", b"alpha bytes SYN-A readable words")
        job_b = store.enqueue("u1", "SYN-1", "b.hl7", b"beta bytes SYN-B readable words")
        real_claim = store.claim_specific

        def flaky(job_id: str) -> Any:
            if job_id == job_a["id"]:
                raise OSError("index unavailable")
            return real_claim(job_id)

        monkeypatch.setattr(store, "claim_specific", flaky)
        worker._run_job(job_a["id"])
        assert executed == []
        back_a = store.get(job_a["id"])
        assert back_a is not None and back_a["status"] == "failed"
        assert back_a.get("reason") == "store_unavailable"
        back_b = store.get(job_b["id"])
        assert back_b is not None and back_b["status"] == "queued"
        monkeypatch.setattr(store, "claim_specific", real_claim)
        worker._run_job(job_b["id"])
        done_b = store.get(job_b["id"])
        assert done_b is not None and done_b["status"] == "manual-review"
        assert len(executed) == 1
    finally:
        worker.close()


def test_first_failure_second_completes_no_wedge(tmp_path: Path) -> None:
    store, _, _ = _store(tmp_path)
    calls = {"n": 0}

    def runner(src: Path, out: Path, allow: bool) -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return _review_runner(src, out, allow)

    worker = UploadWorker(store, runner=runner)
    try:
        j1 = store.enqueue("u1", "SYN-1", "a.hl7", b"readable synthetic ward note alpha words")
        j2 = store.enqueue("u1", "SYN-1", "b.hl7", b"readable synthetic ward note beta words")
        worker._run_job(j1["id"])
        worker._run_job(j2["id"])
        b1 = store.get(j1["id"])
        b2 = store.get(j2["id"])
        assert b1 is not None and b1["status"] == "failed"
        assert b2 is not None and b2["status"] == "manual-review"
    finally:
        worker.close()


def test_cancel_persists_meta_across_index_loss(tmp_path: Path) -> None:
    store, store_dir, keys = _store(tmp_path)
    body = b"cancel persist bytes SYN-C words here"
    digest = hashlib.sha256(body).hexdigest()
    job = store.enqueue("u1", "SYN-1", "c.hl7", body)
    assert store.cancel(job["id"], "u1") is True
    meta_raw = (store_dir / job["id"] / "meta.json").read_bytes()
    meta = json.loads(meta_raw.decode("utf-8"))
    assert meta["status"] == "cancelled"
    assert meta["id"] == job["id"]
    (store_dir / "index.json").unlink()
    reopened = UploadStore(store_dir, keys)
    back = reopened.get(job["id"])
    assert back is not None and back["status"] == "cancelled"
    assert back["sha256"] == digest
    assert reopened.read_original(job["id"]) == body


def test_cancel_auth_and_state_guards(tmp_path: Path) -> None:
    store, _, _ = _store(tmp_path)
    job = store.enqueue("u1", "SYN-1", "a.hl7", b"readable guard bytes SYN-G words")
    assert store.cancel(job["id"], "u2") is False
    assert store.cancel("0" * 32, "u1") is False
    still = store.get(job["id"])
    assert still is not None and still["status"] == "queued"
    assert store.cancel(job["id"], "u1") is True
    assert store.cancel(job["id"], "u1") is False
    assert store.claim_specific(job["id"]) is None
    mine = store.list_for("u1", "SYN-1")
    assert any(j["id"] == job["id"] for j in mine)
    other = store.list_for("u2", "SYN-1")
    assert all(j["id"] != job["id"] for j in other)
    fresh = store.get(job["id"])
    assert fresh is not None and fresh["owner"] == "u1" and fresh["status"] == "cancelled"
