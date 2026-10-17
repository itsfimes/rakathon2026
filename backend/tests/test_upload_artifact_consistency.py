from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from rakathon_backend.converter.planner import RecipeCache
from rakathon_backend.uploads.crypto import generate_key_file
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.uploads.store_export import MAX_EXPORT_BYTES
from rakathon_backend.uploads.worker_collect import collect_result
from rakathon_backend.web.config import (
    MAX_ARTIFACT_BYTES,
    MAX_BODY_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_UPLOAD_BYTES,
)

CASE = "SYN-000001"


def _bundle(patient_id: str) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": {"resourceType": "Patient", "id": patient_id},
                "request": {"method": "PUT", "url": f"Patient/{patient_id}"},
            }
        ],
    }


def _outcome() -> dict[str, Any]:
    return {
        "resourceType": "OperationOutcome",
        "issue": [{"severity": "error", "code": "processing", "diagnostics": "needs human"}],
    }


def _setup(tmp_path: Path, payload: bytes) -> tuple[UploadStore, str, str]:
    store_dir = tmp_path / "persist"
    store_dir.mkdir(mode=0o700)
    keys = generate_key_file(store_dir / "store.key")
    store = UploadStore(store_dir, keys)
    job = store.enqueue("doc1", CASE, "note.hl7", payload)
    return (store, str(job["id"]), str(job["sha256"]))


def _write_out(out_dir: Path, result: dict[str, Any], prov: dict[str, Any], secondary: Any) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (out_dir / "provenance.json").write_text(json.dumps(prov), encoding="utf-8")
    if secondary is not None:
        if isinstance(secondary, (dict, list)):
            (out_dir / "bundle.json").write_text(json.dumps(secondary), encoding="utf-8")
        else:
            (out_dir / "bundle.json").write_bytes(bytes(secondary))


def _result(bundle: Any, sha: str, *, complete: bool) -> dict[str, Any]:
    return {
        "status": "complete" if complete else "manual-review",
        "bundle": bundle,
        "issues": [],
        "evidence": [],
        "needsReview": True,
        "writeEligible": False,
        "persistence": "not-written",
        "model": {"providerId": "p", "model": "m", "present": bool(complete)},
        "source": {"sha256": sha},
        "adaptive": {"newFormat": False, "recipeReuse": False, "plannerMode": "fallback"},
    }


def test_divergent_secondary_bundle_refused_and_not_cached(tmp_path: Path) -> None:
    body = b"synthetic divergent case SYN-71 with words"
    store, job_id, sha = _setup(tmp_path, body)
    primary = _bundle("p1")
    _write_out(
        tmp_path / "out", _result(primary, sha, complete=True), {"sourceSha256": sha}, _bundle("p2")
    )
    collect_result(store, RecipeCache(None), False, job_id, tmp_path / "out", 0)
    job = store.get(job_id)
    assert job is not None and job["status"] == "failed" and job.get("reason") == "invalid_fhir"
    assert store.read_result_blob(job_id, "bundle") is None
    assert store.read_original(job_id) == body


def test_operation_outcome_rejected_in_collect(tmp_path: Path) -> None:
    body = b"synthetic outcome case SYN-72 with words"
    store, job_id, sha = _setup(tmp_path, body)
    outcome = _outcome()
    _write_out(
        tmp_path / "out", _result(outcome, sha, complete=False), {"sourceSha256": sha}, outcome
    )
    collect_result(store, RecipeCache(None), False, job_id, tmp_path / "out", 0)
    job = store.get(job_id)
    assert job is not None and job["status"] == "failed" and job.get("reason") == "invalid_fhir"
    assert store.read_result_blob(job_id, "bundle") is None
    assert store.read_original(job_id) == body


def test_canonical_bundle_persisted_and_exported(tmp_path: Path) -> None:
    body = b"synthetic canonical case SYN-73 with words"
    store, job_id, sha = _setup(tmp_path, body)
    primary = _bundle("p1")
    _write_out(
        tmp_path / "out", _result(primary, sha, complete=True), {"sourceSha256": sha}, primary
    )
    collect_result(store, RecipeCache(None), False, job_id, tmp_path / "out", 0)
    job = store.get(job_id)
    assert job is not None and job["status"] == "complete"
    expected = json.dumps(primary, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert store.read_result_blob(job_id, "bundle") == expected
    blob = store.export_zip(job_id)
    assert blob is not None
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        assert zf.read("original.bin") == body
        assert json.loads(zf.read("bundle.json").decode("utf-8")) == primary


def test_artifact_cap_aligns_with_export_and_other_caps_fixed() -> None:
    assert MAX_ARTIFACT_BYTES == MAX_EXPORT_BYTES == 12 * 1024 * 1024
    assert MAX_UPLOAD_BYTES == 5 * 1024 * 1024
    assert MAX_BODY_BYTES == 16 * 1024
    assert MAX_RESPONSE_BYTES == 1024 * 1024
