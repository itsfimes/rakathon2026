from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.common.errors import ContractError
from rakathon_backend.converter.model_draft import build_model_draft
from rakathon_backend.uploads.crypto import generate_key_file
from rakathon_backend.uploads.review_store import ReviewStore
from rakathon_backend.uploads.store import UploadStore

OWNER = "reviewer-1"
CASE = "SYN-000001"
ALIAS = "model-p9"


def _bundle(obs_id: str = "o1") -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": {"resourceType": "Patient", "id": ALIAS},
                "request": {"method": "PUT", "url": "Patient/" + ALIAS},
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": obs_id,
                    "status": "final",
                    "code": {"text": "GLU"},
                    "subject": {"reference": "Patient/" + ALIAS},
                },
                "request": {"method": "PUT", "url": "Observation/" + obs_id},
            },
        ],
    }


def _stores(tmp_path: Path) -> tuple[UploadStore, Path, Any]:
    d = tmp_path / "s"
    d.mkdir(mode=0o700)
    keys = generate_key_file(d / "store.key")
    return (UploadStore(d, keys), d, keys)


def _job_with_draft(store: UploadStore, body: bytes) -> dict[str, Any]:
    job = store.enqueue(OWNER, CASE, "n.txt", body)
    job_id = str(job["id"])
    sha = str(job["sha256"])
    raw = json.dumps({"status": "complete", "bundle": _bundle()})
    draft = build_model_draft(raw, sha, "p", "m")
    store.write_result_blob(job_id, "model-draft", json.dumps(draft).encode("utf-8"))
    store.finish(job_id, "complete")
    return store.get(job_id) or {}


def _receipt() -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction-response",
        "entry": [{"response": {"status": "201 Created", "location": "Observation/x/_history/1"}}],
    }


def test_seed_from_verified_draft(tmp_path: Path) -> None:
    store, _, _ = _stores(tmp_path)
    job = _job_with_draft(store, b"alpha body SYN-000001 words")
    reviews = ReviewStore(store)
    public = reviews.get(str(job["id"]), OWNER)
    assert public["revision"] == 0
    assert public["state"] == "pending"
    assert public["modelDraftAvailable"] is True
    assert public["validation"]["valid"] is True
    assert "Observation" in public["candidateText"]
    assert public["sourceSha256"] == job["sha256"]
    assert reviews.get_model_text(str(job["id"]), OWNER) is not None


def test_invalid_save_allowed_but_never_claimable(tmp_path: Path) -> None:
    store, _, _ = _stores(tmp_path)
    job = _job_with_draft(store, b"beta body SYN-000001 words")
    reviews = ReviewStore(store)
    saved = reviews.save(str(job["id"]), OWNER, 0, "not json at all")
    assert saved["revision"] == 1
    assert saved["state"] == "draft"
    assert saved["validation"]["valid"] is False
    assert saved["validation"]["issues"][0]["code"] in ("bad_payload", "malformed_json")
    with pytest.raises(ContractError) as excinfo:
        reviews.claim_import(str(job["id"]), OWNER, 1, True)
    assert excinfo.value.code == "invalid_candidate"
    again = reviews.get(str(job["id"]), OWNER)
    assert again["state"] == "draft"
    assert again["revision"] == 1


def test_claim_needs_confirmation_and_current_revision(tmp_path: Path) -> None:
    store, _, _ = _stores(tmp_path)
    job = _job_with_draft(store, b"gamma body SYN-000001 words")
    reviews = ReviewStore(store)
    with pytest.raises(ContractError) as excinfo:
        reviews.claim_import(str(job["id"]), OWNER, 0, False)
    assert excinfo.value.code == "confirmation_required"
    with pytest.raises(ContractError) as excinfo2:
        reviews.claim_import(str(job["id"]), OWNER, 9, True)
    assert excinfo2.value.code == "conflict"
    claimed = reviews.claim_import(str(job["id"]), OWNER, 0, True)
    assert claimed["state"] == "importing"
    assert str(claimed["approvalId"]).startswith("rev-")
    with pytest.raises(ContractError) as excinfo3:
        reviews.claim_import(str(job["id"]), OWNER, 0, True)
    assert excinfo3.value.code == "conflict"


def test_concurrent_claims_single_winner(tmp_path: Path) -> None:
    store, _, _ = _stores(tmp_path)
    job = _job_with_draft(store, b"delta body SYN-000001 words")
    reviews = ReviewStore(store)
    wins: list[str] = []
    errors: list[str] = []
    lock = threading.Lock()

    def _try() -> None:
        try:
            out = reviews.claim_import(str(job["id"]), OWNER, 0, True)
            with lock:
                wins.append(str(out["approvalId"]))
        except ContractError as exc:
            with lock:
                errors.append(exc.code)

    threads = [threading.Thread(target=_try) for _ in range(8)]
    for item in threads:
        item.start()
    for item in threads:
        item.join()
    assert len(wins) == 1
    assert len(errors) == 7
    assert all(code == "conflict" for code in errors)


def test_source_immutable_and_model_unchanged(tmp_path: Path) -> None:
    store, _, _ = _stores(tmp_path)
    body = b"epsilon body SYN-000001 words"
    job = _job_with_draft(store, b"epsilon body SYN-000001 words")
    job_id = str(job["id"])
    before_draft = store.read_result_blob(job_id, "model-draft")
    reviews = ReviewStore(store)
    saved = reviews.save(job_id, OWNER, 0, json.dumps(_bundle("o9")))
    assert saved["revision"] == 1
    live = store.get(job_id)
    assert live is not None
    assert live["sha256"] == job["sha256"]
    assert live["sourceUrn"] == job["sourceUrn"]
    assert live["caseId"] == CASE
    assert store.read_result_blob(job_id, "model-draft") == before_draft
    assert store.read_original(job_id) == body


def test_import_success_receipt_and_export(tmp_path: Path) -> None:
    store, _, _ = _stores(tmp_path)
    job = _job_with_draft(store, b"zeta body SYN-000001 words")
    job_id = str(job["id"])
    reviews = ReviewStore(store)
    claimed = reviews.claim_import(job_id, OWNER, 0, True)
    approval = str(claimed["approvalId"])
    with pytest.raises(ContractError):
        reviews.save(job_id, OWNER, 0, json.dumps(_bundle("o2")))
    done = reviews.record_import(job_id, approval, _receipt())
    assert done["state"] == "imported"
    assert done["importReceipt"] is not None
    again = reviews.claim_import(job_id, OWNER, int(done["revision"]), True)
    assert again.get("alreadyImported") is True
    assert again["approvalId"] == approval
    with pytest.raises(ContractError):
        reviews.save(job_id, OWNER, int(done["revision"]), json.dumps(_bundle("o3")))
    arts = reviews.export_artifacts(job_id, OWNER)
    assert set(arts.keys()) == {
        "review-draft.txt",
        "review.json",
        "review-audit.json",
        "approved-bundle.json",
        "import-receipt.json",
    }
    approved = json.loads(arts["approved-bundle.json"].decode("utf-8"))
    assert approved["resourceType"] == "Bundle"
    assert all(item["resource"]["resourceType"] != "Patient" for item in approved["entry"])
    pre = reviews.export_artifacts(job_id, OWNER)
    assert json.loads(pre["review.json"].decode("utf-8"))["state"] == "imported"


def test_explicit_failure_reeditable_uncertain_blocked(tmp_path: Path) -> None:
    store, _, _ = _stores(tmp_path)
    job = _job_with_draft(store, b"eta body SYN-000001 words")
    job_id = str(job["id"])
    reviews = ReviewStore(store)
    claimed = reviews.claim_import(job_id, OWNER, 0, True)
    failed = reviews.record_failure(job_id, str(claimed["approvalId"]), "send_failed")
    assert failed["state"] == "import-failed"
    fixed = reviews.save(job_id, OWNER, int(failed["revision"]), json.dumps(_bundle("o7")))
    assert fixed["state"] == "draft"
    claimed2 = reviews.claim_import(job_id, OWNER, int(fixed["revision"]), True)
    reviews.record_failure(job_id, str(claimed2["approvalId"]), "timeout", uncertain=True)
    current = reviews.get(job_id, OWNER)
    assert current["state"] == "import-uncertain"
    with pytest.raises(ContractError):
        reviews.save(job_id, OWNER, int(current["revision"]), json.dumps(_bundle("o8")))
    with pytest.raises(ContractError):
        reviews.claim_import(job_id, OWNER, int(current["revision"]), True)


def test_restart_preserves_draft_and_marks_uncertain(tmp_path: Path) -> None:
    store, store_dir, keys = _stores(tmp_path)
    body = b"theta body SYN-000001 words"
    job = _job_with_draft(store, body)
    job_id = str(job["id"])
    reviews = ReviewStore(store)
    saved = reviews.save(job_id, OWNER, 0, json.dumps(_bundle("o5")))
    assert saved["revision"] == 1
    claimed = reviews.claim_import(job_id, OWNER, 1, True)
    approval = str(claimed["approvalId"])
    reopened = ReviewStore(UploadStore(store_dir, keys))
    current = reopened.get(job_id, OWNER)
    assert current["state"] == "import-uncertain"
    assert current["revision"] == 1
    assert "o5" in current["candidateText"]
    assert reopened._uploads.read_original(job_id) == body
    done = reopened.record_import(job_id, approval, _receipt())
    assert done["state"] == "imported"


def test_legacy_missing_and_bundle_fallback(tmp_path: Path) -> None:
    store, _, _ = _stores(tmp_path)
    reviews = ReviewStore(store)
    bare = store.enqueue(OWNER, CASE, "b.txt", b"iota body SYN-000001 words")
    store.finish(str(bare["id"]), "manual-review")
    public = reviews.get(str(bare["id"]), OWNER)
    assert public["candidateText"] == ""
    assert public["modelDraftAvailable"] is False
    assert public["modelDraftReason"] == "legacy-draft-missing"
    assert public["validation"]["valid"] is False
    job2 = store.enqueue(OWNER, CASE, "c.txt", b"kappa body SYN-000001 words")
    store.write_result_blob(str(job2["id"]), "bundle", json.dumps(_bundle()).encode("utf-8"))
    store.finish(str(job2["id"]), "complete")
    legacy = reviews.get(str(job2["id"]), OWNER)
    assert legacy["modelDraftAvailable"] is False
    assert legacy["modelDraftReason"] == "legacy-bundle-fallback"
    assert legacy["validation"]["valid"] is True


def test_guards_owner_queued_and_stale(tmp_path: Path) -> None:
    store, _, _ = _stores(tmp_path)
    job = _job_with_draft(store, b"lambda body SYN-000001 words")
    reviews = ReviewStore(store)
    with pytest.raises(ContractError) as excinfo:
        reviews.get(str(job["id"]), "someone-else")
    assert excinfo.value.code == "forbidden"
    with pytest.raises(ContractError) as excinfo2:
        reviews.get("0" * 32, OWNER)
    assert excinfo2.value.code == "not_found"
    queued = store.enqueue(OWNER, CASE, "q.txt", b"mu body SYN-000001 words")
    with pytest.raises(ContractError) as excinfo3:
        reviews.get(str(queued["id"]), OWNER)
    assert excinfo3.value.code == "review_unavailable"
    with pytest.raises(ContractError) as excinfo4:
        reviews.save(str(job["id"]), OWNER, 7, json.dumps(_bundle()))
    assert excinfo4.value.code == "conflict"
    with pytest.raises(ContractError) as excinfo5:
        reviews.record_import(str(job["id"]), "rev-bad", _receipt())
    assert excinfo5.value.code == "approval_mismatch"
