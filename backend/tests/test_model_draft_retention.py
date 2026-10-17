from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import rakathon_backend.converter.cli as cli_mod
from rakathon_backend.converter.agent import AgentError
from rakathon_backend.converter.cli import main
from rakathon_backend.converter.model_draft import MAX_MODEL_OUTPUT_BYTES, build_model_draft
from rakathon_backend.converter.planner import RecipeCache
from rakathon_backend.uploads.crypto import generate_key_file
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.uploads.worker_collect import collect_result

MOCK_NOTE = "OFFLINE UNIT TEST ONLY: mock model text, never demo output."


def _input(tmp_path: Path, body: bytes | None = None) -> Path:
    target = tmp_path / "doc.txt"
    target.write_bytes(body if body is not None else b"PAT ZEBRA SYN-000001 GLUCOSE 102 mg/dL")
    return target


def _secret(tmp_path: Path) -> Path:
    target = tmp_path / "key"
    target.write_text("RAKATHON_AI_API_KEY=mock-key-123", encoding="utf-8")
    target.chmod(0o600)
    return target


def _mock_complete() -> str:
    assert MOCK_NOTE
    return json.dumps(
        {
            "status": "complete",
            "bundle": {
                "resourceType": "Bundle",
                "type": "transaction",
                "entry": [
                    {
                        "resource": {"resourceType": "Patient", "id": "p1"},
                        "request": {"method": "PUT", "url": "Patient/p1"},
                    },
                    {
                        "resource": {
                            "resourceType": "DocumentReference",
                            "id": "d1",
                            "status": "current",
                            "content": [{"attachment": {"data": "aGVsbG8="}}],
                        },
                        "request": {"method": "PUT", "url": "DocumentReference/d1"},
                    },
                ],
            },
            "issues": [],
            "evidence": [
                {
                    "resourceType": "Patient",
                    "id": "p1",
                    "sourcePage": 1,
                    "literalQuote": "PAT ZEBRA SYN-000001",
                    "field": "/id",
                },
                {
                    "resourceType": "DocumentReference",
                    "id": "d1",
                    "sourcePage": 1,
                    "literalQuote": "GLUCOSE 102 mg/dL",
                    "field": "/content/0/attachment/data",
                },
            ],
        }
    )


def _setup_store(tmp_path: Path, body: bytes) -> tuple[UploadStore, str, str]:
    store_dir = tmp_path / "persist"
    store_dir.mkdir(mode=0o700)
    keys = generate_key_file(store_dir / "store.key")
    store = UploadStore(store_dir, keys)
    job = store.enqueue("doc1", "SYN-000001", "note.txt", body)
    return (store, str(job["id"]), str(job["sha256"]))


def _collect_job(
    tmp_path: Path, body: bytes, out_dir: Path, code: int
) -> tuple[UploadStore, str, dict[str, Any] | None]:
    store, job_id, _ = _setup_store(tmp_path, body)
    collect_result(store, RecipeCache(None), True, job_id, out_dir, code)
    job = store.get(job_id)
    assert job is not None
    return (store, job_id, job)


def test_valid_draft_retained_sealed_and_original_readonly(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    assert MOCK_NOTE
    raw = _mock_complete()
    monkeypatch.setattr(cli_mod, "run_model_once", lambda *a, **k: raw)
    body = b"PAT ZEBRA SYN-000001 GLUCOSE 102 mg/dL"
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(_input(tmp_path, body)),
            "--output",
            str(out),
            "--allow-azure",
            "--secret-file",
            str(_secret(tmp_path)),
        ]
    )
    assert code == 0
    draft_path = out / "model-draft.json"
    assert draft_path.is_file()
    assert stat.S_IMODE(os.stat(draft_path).st_mode) == 0o600
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert draft["version"] == 1
    assert set(draft.keys()) == {
        "version",
        "sourceSha256",
        "modelOutputText",
        "candidateText",
        "model",
    }
    assert draft["modelOutputText"] == raw
    assert "Patient" in draft["candidateText"]
    assert draft["model"] == {"providerId": "rakathon-azure", "model": "gpt-6-luna-dz-eu"}
    assert "mock-key-123" not in draft_path.read_text(encoding="utf-8")
    captured = capsys.readouterr()
    assert "mock-key-123" not in captured.out + captured.err
    assert raw not in captured.out
    store, job_id, job = _collect_job(tmp_path, body, out, 0)
    assert job is not None and job["status"] == "complete"
    sealed = store.read_result_blob(job_id, "model-draft")
    assert sealed is not None
    assert sealed == draft_path.read_bytes()
    assert store.read_original(job_id) == body
    assert store.read_result_blob(job_id, "bundle") is not None


def test_rejected_draft_retained_sealed(tmp_path: Path, monkeypatch: Any) -> None:
    assert MOCK_NOTE
    raw = "not json at all, just prose"
    monkeypatch.setattr(cli_mod, "run_model_once", lambda *a, **k: raw)
    body = b"PAT ZEBRA SYN-000001 GLUCOSE 102 mg/dL"
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(_input(tmp_path, body)),
            "--output",
            str(out),
            "--allow-azure",
            "--secret-file",
            str(_secret(tmp_path)),
        ]
    )
    assert code == 3
    draft_path = out / "model-draft.json"
    assert draft_path.is_file()
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert draft["version"] == 1
    assert draft["modelOutputText"] == raw
    assert draft["candidateText"] == raw
    assert not (out / "bundle.json").exists()
    store, job_id, job = _collect_job(tmp_path, body, out, 3)
    assert job is not None and job["status"] == "manual-review"
    sealed = store.read_result_blob(job_id, "model-draft")
    assert sealed == draft_path.read_bytes()
    assert store.read_original(job_id) == body
    assert store.read_result_blob(job_id, "bundle") is None


def test_wrong_sha_draft_ignored_and_never_cached(tmp_path: Path, monkeypatch: Any) -> None:
    assert MOCK_NOTE
    raw = _mock_complete()
    monkeypatch.setattr(cli_mod, "run_model_once", lambda *a, **k: raw)
    body = b"PAT ZEBRA SYN-000001 GLUCOSE 102 mg/dL"
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(_input(tmp_path, body)),
            "--output",
            str(out),
            "--allow-azure",
            "--secret-file",
            str(_secret(tmp_path)),
        ]
    )
    assert code == 0
    draft_path = out / "model-draft.json"
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    draft["sourceSha256"] = "0" * 64
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    cache_file = tmp_path / "cache.json"
    store, job_id, _ = _setup_store(tmp_path, body)
    collect_result(store, RecipeCache(cache_file), True, job_id, out, 0)
    assert store.read_result_blob(job_id, "model-draft") is None
    assert store.read_original(job_id) == body
    assert not cache_file.exists() or cache_file.read_bytes().strip() in (b"", b"{}")


def test_no_snapshot_when_model_produces_no_output(tmp_path: Path, monkeypatch: Any) -> None:
    assert MOCK_NOTE

    def _fail(*a: Any, **k: Any) -> str:
        raise AgentError("inference_failed", "mock provider failure")

    monkeypatch.setattr(cli_mod, "run_model_once", _fail)
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(_input(tmp_path)),
            "--output",
            str(out),
            "--allow-azure",
            "--secret-file",
            str(_secret(tmp_path)),
        ]
    )
    assert code == 0
    assert not (out / "model-draft.json").exists()
    assert (out / "result.json").is_file()


def test_empty_output_produces_no_snapshot(tmp_path: Path, monkeypatch: Any) -> None:
    assert MOCK_NOTE
    monkeypatch.setattr(cli_mod, "run_model_once", lambda *a, **k: "   ")
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(_input(tmp_path)),
            "--output",
            str(out),
            "--allow-azure",
            "--secret-file",
            str(_secret(tmp_path)),
        ]
    )
    assert code == 3
    assert not (out / "model-draft.json").exists()


def test_draft_output_bounded() -> None:
    assert MOCK_NOTE
    big = "x" * (MAX_MODEL_OUTPUT_BYTES + 1000)
    draft = build_model_draft(big, "a" * 64, "p", "m")
    assert len(draft["modelOutputText"].encode("utf-8")) <= MAX_MODEL_OUTPUT_BYTES
    assert len(draft["candidateText"].encode("utf-8")) <= MAX_MODEL_OUTPUT_BYTES
    assert set(draft.keys()) == {
        "version",
        "sourceSha256",
        "modelOutputText",
        "candidateText",
        "model",
    }
