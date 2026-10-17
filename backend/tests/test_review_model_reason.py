from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rakathon_backend.uploads.crypto import generate_key_file
from rakathon_backend.uploads.review_state import persist_state, public_view, read_state, seed_state
from rakathon_backend.uploads.review_store import ReviewStore
from rakathon_backend.uploads.store import UploadStore

OWNER = "reviewer-1"
CASE = "SYN-000001"


def _stores(tmp_path: Path) -> UploadStore:
    d = tmp_path / "s"
    d.mkdir(mode=0o700)
    keys = generate_key_file(d / "store.key")
    return UploadStore(d, keys)


def _bundle() -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": {"resourceType": "Patient", "id": "model-p9"},
                "request": {"method": "PUT", "url": "Patient/model-p9"},
            }
        ],
    }


def _transcription_doc(sha: str) -> dict[str, Any]:
    return {
        "version": 1,
        "sourceSha256": sha,
        "untrusted": True,
        "method": "opencode-native-files",
        "modelOutputText": "transcribed SYN-000001",
        "pages": ["hello"],
        "extractSha256": hashlib.sha256(b"hello").hexdigest(),
    }


def test_image_no_ocr_not_legacy(tmp_path: Path) -> None:
    store = _stores(tmp_path)
    job = store.enqueue(OWNER, CASE, "scan.png", b"image bytes SYN-000001 words")
    job_id = str(job["id"])
    store.finish(
        job_id,
        "manual-review",
        {
            "issues": [
                {"code": "image_no_ocr", "message": "image input needs human transcription"}
            ],
            "fhirStatus": "manual-review",
            "modelMode": "azure",
        },
    )
    stored = store.get(job_id)
    assert stored is not None
    state = seed_state(store, stored)
    assert state["modelDraftReason"] == "model-not-invoked:image_no_ocr"
    assert state["modelDraftReason"] != "legacy-draft-missing"


def test_genuine_legacy_missing_draft(tmp_path: Path) -> None:
    store = _stores(tmp_path)
    job = store.enqueue(OWNER, CASE, "old.txt", b"old body SYN-000001 words")
    job_id = str(job["id"])
    store.finish(job_id, "manual-review")
    stored = store.get(job_id)
    assert stored is not None
    state = seed_state(store, stored)
    assert state["modelDraftReason"] == "legacy-draft-missing"
    assert state["candidateText"] == ""


def test_provider_failure_reason_has_no_patient_content(tmp_path: Path) -> None:
    store = _stores(tmp_path)
    job = store.enqueue(OWNER, CASE, "scan.png", b"another body SYN-000001 words")
    job_id = str(job["id"])
    store.finish(job_id, "failed", {"reason": "session_failed"})
    stored = store.get(job_id)
    assert stored is not None
    state = seed_state(store, stored)
    assert state["modelDraftReason"] == "model-failed:session_failed"
    assert "SYN-000001" not in str(state["modelDraftReason"])
    assert len(str(state["modelDraftReason"])) <= 64


def test_legacy_bundle_fallback_preserved(tmp_path: Path) -> None:
    store = _stores(tmp_path)
    job = store.enqueue(OWNER, CASE, "c.txt", b"kappa body SYN-000001 words")
    job_id = str(job["id"])
    store.write_result_blob(job_id, "bundle", json.dumps(_bundle()).encode("utf-8"))
    store.finish(job_id, "complete")
    stored = store.get(job_id)
    assert stored is not None
    state = seed_state(store, stored)
    assert state["modelDraftReason"] == "legacy-bundle-fallback"


def test_untrusted_flag_only_with_verified_artifact(tmp_path: Path) -> None:
    store = _stores(tmp_path)
    job = store.enqueue(OWNER, CASE, "n.png", b"flag body SYN-000001 words")
    job_id = str(job["id"])
    store.finish(job_id, "manual-review", {"issues": [{"code": "fhir_failed", "message": "x"}]})
    stored = store.get(job_id)
    assert stored is not None
    bare = seed_state(store, stored)
    assert bare["sourceMethod"] is None
    assert bare["transcriptionUntrusted"] is False
    view_bare = public_view(bare, stored)
    assert view_bare["sourceMethod"] is None
    assert view_bare["transcriptionUntrusted"] is False
    assert view_bare["validation"]["sourceMethod"] is None
    assert view_bare["validation"]["transcriptionUntrusted"] is False
    job2 = store.enqueue(OWNER, CASE, "n2.png", b"flag body two SYN-000001 words")
    job2_id = str(job2["id"])
    sha2 = str(job2["sha256"])
    store.finish(job2_id, "manual-review", {"issues": [{"code": "fhir_failed", "message": "x"}]})
    store.write_result_blob(job2_id, "transcription", json.dumps(_transcription_doc(sha2)).encode())
    store.write_result_blob(
        job2_id, "provenance", json.dumps({"sourceSha256": sha2}).encode("utf-8")
    )
    reviews = ReviewStore(store)
    public = reviews.get(job2_id, OWNER)
    assert public["sourceMethod"] == "opencode-native-files"
    assert public["transcriptionUntrusted"] is True
    assert public["validation"]["sourceMethod"] == "opencode-native-files"
    assert public["validation"]["transcriptionUntrusted"] is True


def test_transcription_only_draft_available(tmp_path: Path) -> None:
    store = _stores(tmp_path)
    job = store.enqueue(OWNER, CASE, "scan.png", b"ocr transcript body SYN-000001 words")
    job_id = str(job["id"])
    sha = str(job["sha256"])
    draft = {
        "version": 1,
        "sourceSha256": sha,
        "modelOutputText": "transcribed SYN-000001",
        "candidateText": "",
        "model": {"providerId": "azure", "model": "test-model"},
    }
    store.write_result_blob(job_id, "model-draft", json.dumps(draft).encode("utf-8"))
    store.write_result_blob(job_id, "bundle", json.dumps(_bundle()).encode("utf-8"))
    store.finish(job_id, "manual-review")
    stored = store.get(job_id)
    assert stored is not None
    state = seed_state(store, stored)
    assert state["modelDraftAvailable"] is True
    assert state["modelDraftReason"] is None
    assert state["candidateText"] == ""
    assert state["importReceipt"] is None
    view = public_view(state, stored)
    assert view["modelDraftAvailable"] is True
    assert view["modelDraftReason"] is None
    assert view["validation"]["valid"] is False
    assert view["validation"]["modelDraftAvailable"] is True
    assert view["importReceipt"] is None


def test_persisted_legacy_missing_public_derived(tmp_path: Path) -> None:
    store = _stores(tmp_path)
    job = store.enqueue(OWNER, CASE, "scan.png", b"legacy public body SYN-000001 words")
    job_id = str(job["id"])
    store.finish(
        job_id,
        "manual-review",
        {
            "issues": [
                {"code": "image_no_ocr", "message": "image input needs human transcription"}
            ],
            "fhirStatus": "manual-review",
            "modelMode": "azure",
        },
    )
    stored = store.get(job_id)
    assert stored is not None
    state = seed_state(store, stored)
    assert state["modelDraftReason"] == "model-not-invoked:image_no_ocr"
    state["modelDraftReason"] = "legacy-draft-missing"
    persist_state(store, job_id, state)
    saved = read_state(store, job_id)
    assert saved is not None
    assert saved["modelDraftReason"] == "legacy-draft-missing"
    history_len = len(saved["history"])
    revision = int(saved["revision"])
    candidate = str(saved["candidateText"])
    view = public_view(saved, stored)
    assert view["modelDraftReason"] == "model-not-invoked:image_no_ocr"
    assert view["candidateText"] == candidate
    assert view["revision"] == revision
    assert saved["modelDraftReason"] == "legacy-draft-missing"
    fresh = read_state(store, job_id)
    assert fresh is not None
    assert fresh["modelDraftReason"] == "legacy-draft-missing"
    assert fresh["candidateText"] == candidate
    assert fresh["revision"] == revision
    assert len(fresh["history"]) == history_len


def test_unverified_transcription_never_sets_flag(tmp_path: Path) -> None:
    store = _stores(tmp_path)
    job = store.enqueue(OWNER, CASE, "m.png", b"unverified body SYN-000001 words")
    job_id = str(job["id"])
    store.finish(job_id, "manual-review")
    stored = store.get(job_id)
    assert stored is not None
    bad = _transcription_doc("0" * 64)
    store.write_result_blob(job_id, "transcription", json.dumps(bad).encode("utf-8"))
    state = seed_state(store, stored)
    assert state["sourceMethod"] is None
    assert state["transcriptionUntrusted"] is False
    assert public_view(state, stored)["transcriptionUntrusted"] is False
