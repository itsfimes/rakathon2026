from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from rakathon_backend.converter.model_draft import build_model_draft
from rakathon_backend.converter.planner import RecipeCache
from rakathon_backend.uploads.crypto import generate_key_file
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.uploads.transcription_artifact import (
    MAX_TRANSCRIPTION_READ_BYTES,
    is_valid_transcription,
    is_valid_transcription_bytes,
    parse_transcription_bytes,
)
from rakathon_backend.uploads.worker_collect import collect_result

CASE = "SYN-000001"


def _bundle(patient_id: str) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": {"resourceType": "Patient", "id": patient_id},
                "request": {"method": "PUT", "url": "Patient/" + patient_id},
            }
        ],
    }


def _setup(tmp_path: Path, payload: bytes) -> tuple[UploadStore, str, str]:
    store_dir = tmp_path / "persist"
    store_dir.mkdir(mode=0o700)
    keys = generate_key_file(store_dir / "store.key")
    store = UploadStore(store_dir, keys)
    job = store.enqueue("doc1", CASE, "note.png", payload)
    return (store, str(job["id"]), str(job["sha256"]))


def _doc(sha: str, extract: str | None = None) -> dict[str, Any]:
    digest = extract if extract is not None else hashlib.sha256(b"page-one").hexdigest()
    return {
        "version": 1,
        "sourceSha256": sha,
        "untrusted": True,
        "method": "opencode-native-files",
        "modelOutputText": "transcribed text SYN-000001",
        "pages": ["page-one text"],
        "extractSha256": digest,
    }


def _result(bundle: Any, sha: str, complete: bool) -> dict[str, Any]:
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


def _write_out(
    out_dir: Path,
    result: dict[str, Any],
    prov: dict[str, Any],
    secondary: Any,
    transcription: bytes | None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (out_dir / "provenance.json").write_text(json.dumps(prov), encoding="utf-8")
    if secondary is not None:
        (out_dir / "bundle.json").write_text(json.dumps(secondary), encoding="utf-8")
    if transcription is not None:
        (out_dir / "transcription.json").write_bytes(transcription)


def test_complete_retains_transcription_and_draft(tmp_path: Path) -> None:
    body = b"synthetic complete body SYN-000001 words"
    store, job_id, sha = _setup(tmp_path, body)
    draft = build_model_draft(json.dumps({"status": "ok"}), sha, "p", "m")
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "model-draft.json").write_text(json.dumps(draft), encoding="utf-8")
    primary = _bundle("p1")
    raw = json.dumps(_doc(sha)).encode("utf-8")
    _write_out(out, _result(primary, sha, True), {"sourceSha256": sha}, primary, raw)
    collect_result(store, RecipeCache(None), False, job_id, out, 0)
    job = store.get(job_id)
    assert job is not None and job["status"] == "complete"
    assert store.read_result_blob(job_id, "transcription") == raw
    assert store.read_result_blob(job_id, "model-draft") is not None
    assert store.read_original(job_id) == body


def test_manual_retains_transcription(tmp_path: Path) -> None:
    body = b"synthetic manual body SYN-000001 words"
    store, job_id, sha = _setup(tmp_path, body)
    raw = json.dumps(_doc(sha)).encode("utf-8")
    _write_out(
        tmp_path / "out",
        _result(None, sha, False),
        {"sourceSha256": sha},
        None,
        raw,
    )
    collect_result(store, RecipeCache(None), False, job_id, tmp_path / "out", 0)
    job = store.get(job_id)
    assert job is not None and job["status"] == "manual-review"
    assert store.read_result_blob(job_id, "transcription") == raw


def test_rejected_result_still_retains_valid_transcription(tmp_path: Path) -> None:
    body = b"synthetic rejected body SYN-000001 words"
    store, job_id, sha = _setup(tmp_path, body)
    outcome = {"resourceType": "OperationOutcome", "issue": [{"severity": "error"}]}
    raw = json.dumps(_doc(sha)).encode("utf-8")
    _write_out(
        tmp_path / "out",
        _result(outcome, sha, False),
        {"sourceSha256": sha},
        outcome,
        raw,
    )
    collect_result(store, RecipeCache(None), False, job_id, tmp_path / "out", 0)
    job = store.get(job_id)
    assert job is not None and job["status"] == "failed"
    assert store.read_result_blob(job_id, "transcription") == raw
    assert store.read_result_blob(job_id, "bundle") is None


def test_wrong_sha_not_stored(tmp_path: Path) -> None:
    body = b"synthetic wrong sha body SYN-000001 words"
    store, job_id, sha = _setup(tmp_path, body)
    _ = sha
    bad = json.dumps(_doc("0" * 64)).encode("utf-8")
    assert is_valid_transcription_bytes(bad, "1" * 64) is False
    current = store.get(job_id)
    assert current is not None
    expect = str(current["sha256"])
    _write_out(
        tmp_path / "out",
        _result(None, expect, False),
        {"sourceSha256": expect},
        None,
        bad,
    )
    collect_result(store, RecipeCache(None), False, job_id, tmp_path / "out", 0)
    assert store.read_result_blob(job_id, "transcription") is None


def test_unsafe_shapes_not_stored(tmp_path: Path) -> None:
    body = b"synthetic unsafe body SYN-000001 words"
    store, job_id, sha = _setup(tmp_path, body)
    base = _doc(sha)
    variants: list[bytes] = []
    extra = dict(base)
    extra["prompt"] = "evil"
    variants.append(json.dumps(extra).encode("utf-8"))
    wrong_method = dict(base)
    wrong_method["method"] = "other-tool"
    variants.append(json.dumps(wrong_method).encode("utf-8"))
    trusted = dict(base)
    trusted["untrusted"] = False
    variants.append(json.dumps(trusted).encode("utf-8"))
    bad_version = dict(base)
    bad_version["version"] = 2
    variants.append(json.dumps(bad_version).encode("utf-8"))
    dup = (
        '{"version":1,"version":1,"sourceSha256":"'
        + sha
        + '","untrusted":true,"method":"opencode-native-files",'
        + '"modelOutputText":"x","pages":["x"],"extractSha256":null}'
    ).encode("utf-8")
    variants.append(dup)
    nan = (
        '{"version":NaN,"sourceSha256":"'
        + sha
        + '","untrusted":true,"method":"opencode-native-files",'
        + '"modelOutputText":"x","pages":["x"],"extractSha256":null}'
    ).encode("utf-8")
    variants.append(nan)
    for payload in variants:
        assert parse_transcription_bytes(payload, sha) is None
        assert is_valid_transcription_bytes(payload, sha) is False
    out = tmp_path / "out"
    _write_out(
        out,
        _result(None, sha, False),
        {"sourceSha256": sha},
        None,
        variants[0],
    )
    collect_result(store, RecipeCache(None), False, job_id, out, 0)
    assert store.read_result_blob(job_id, "transcription") is None


def test_bounds_not_stored(tmp_path: Path) -> None:
    assert MAX_TRANSCRIPTION_READ_BYTES == 1048576
    body = b"synthetic bounds body SYN-000001 words"
    store, job_id, sha = _setup(tmp_path, body)
    assert is_valid_transcription(_doc(sha), sha) is True
    big_text = "x" * (262144 + 1)
    big = dict(_doc(sha))
    big["modelOutputText"] = big_text
    assert is_valid_transcription(big, sha) is False
    many_pages = dict(_doc(sha))
    many_pages["pages"] = ["a", "b", "c"]
    assert is_valid_transcription(many_pages, sha) is False
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(_result(None, sha, False)), encoding="utf-8")
    (out / "provenance.json").write_text(json.dumps({"sourceSha256": sha}), encoding="utf-8")
    (out / "transcription.json").write_bytes(b"x" * (MAX_TRANSCRIPTION_READ_BYTES + 1))
    collect_result(store, RecipeCache(None), False, job_id, out, 0)
    assert store.read_result_blob(job_id, "transcription") is None


def test_export_only_safe_transcription_and_valid_bundle(tmp_path: Path) -> None:
    body = b"synthetic export body SYN-000001 words"
    store, job_id, sha = _setup(tmp_path, body)
    primary = _bundle("p9")
    raw = json.dumps(_doc(sha)).encode("utf-8")
    _write_out(tmp_path / "out", _result(primary, sha, True), {"sourceSha256": sha}, primary, raw)
    collect_result(store, RecipeCache(None), False, job_id, tmp_path / "out", 0)
    blob = store.export_zip(job_id)
    assert blob is not None
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        assert zf.read("original.bin") == body
        assert json.loads(zf.read("bundle.json").decode("utf-8")) == primary
        assert zf.read("transcription.json") == raw
        names = set(zf.namelist())
        assert "transcription.json" in names
    store2_dir = tmp_path / "s2"
    store2_dir.mkdir(mode=0o700)
    keys2 = generate_key_file(store2_dir / "store.key")
    store2 = UploadStore(store2_dir, keys2)
    job2 = store2.enqueue("doc1", CASE, "n.bin", body)
    job2_id = str(job2["id"])
    store2.write_result_blob(job2_id, "result", b"{}")
    store2.write_result_blob(job2_id, "transcription", b"not-json")
    blob2 = store2.export_zip(job2_id)
    assert blob2 is not None
    with zipfile.ZipFile(io.BytesIO(blob2)) as zf2:
        assert zf2.read("original.bin") == body
        assert "bundle.json" not in set(zf2.namelist())
        assert "transcription.json" not in set(zf2.namelist())
