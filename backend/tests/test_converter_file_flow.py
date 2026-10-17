from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_converter_extract import _minimal_pdf

import rakathon_backend.converter.cli as cli_mod
import rakathon_backend.converter.file_flow as file_flow_mod
from rakathon_backend.converter.cli import main
from rakathon_backend.converter.file_agent import FileModelRun
from rakathon_backend.converter.transcription import build_extracted, parse_transcription


def _png() -> bytes:
    ihdr = struct.pack(">IIBBBBB", 32, 16, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\x00\x00\x00\x00"


def _secret(tmp_path: Path) -> Path:
    target = tmp_path / "key"
    target.write_text("RAKATHON_AI_API_KEY=mock-key", encoding="utf-8")
    target.chmod(0o600)
    return target


def _args(target: Path, out: Path, secret: Path) -> list[str]:
    return [
        "--input",
        str(target),
        "--output",
        str(out),
        "--allow-azure",
        "--secret-file",
        str(secret),
    ]


def _page_text() -> str:
    return "PAT ZEBRA SYN-000001 GLUCOSE 102 mg/dL"


def _mock_complete() -> str:
    patient = {"resourceType": "Patient", "id": "p1"}
    docref = {
        "resourceType": "DocumentReference",
        "id": "d1",
        "status": "current",
        "content": [{"attachment": {"data": "aGVsbG8="}}],
    }
    ev_a = {
        "resourceType": "Patient",
        "id": "p1",
        "sourcePage": 1,
        "literalQuote": "PAT ZEBRA SYN-000001",
        "field": "/id",
    }
    ev_b = {
        "resourceType": "DocumentReference",
        "id": "d1",
        "sourcePage": 1,
        "literalQuote": "GLUCOSE 102 mg/dL",
        "field": "/content/0/attachment/data",
    }
    entry_a = {"resource": patient, "request": {"method": "PUT", "url": "Patient/p1"}}
    entry_b = {"resource": docref, "request": {"method": "PUT", "url": "DocumentReference/d1"}}
    bundle = {"resourceType": "Bundle", "type": "transaction", "entry": [entry_a, entry_b]}
    return json.dumps(
        {"status": "complete", "bundle": bundle, "issues": [], "evidence": [ev_a, ev_b]}
    )


def _meta(sha: str, extract_sha: str | None, count: int) -> dict[str, Any]:
    return {
        "method": "opencode-native-files",
        "untrusted": True,
        "source_sha256": sha,
        "extract_sha256": extract_sha,
        "page_count": count,
        "issues": [],
        "model": "rakathon-azure/m",
    }


def _fake_ok(page_text: str, fhir: str | None = None) -> Callable[..., FileModelRun]:
    payload = _mock_complete() if fhir is None else fhir

    def _run(paths: list[Path], **kwargs: Any) -> FileModelRun:
        original = Path(str(kwargs["original_path"]))
        sha = hashlib.sha256(original.read_bytes()).hexdigest()
        pages = [{"page": i + 1, "text": page_text} for i in range(len(paths))]
        raw = json.dumps({"pages": pages, "issues": []})
        parsed = parse_transcription(raw, page_count=len(paths))
        suffix = original.suffix.lower()
        extracted = build_extracted(
            parsed.pages, source_sha256=sha, suffix=suffix, filename=original.name
        )
        return FileModelRun(
            raw_fhir=payload,
            transcription_raw=raw,
            extracted=extracted,
            transcription_metadata=_meta(sha, extracted.extract_sha256, len(paths)),
            issue_code=None,
        )

    return _run


def _boom_model(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("no AI call allowed")


def test_valid_png_uses_file_lane_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _png()
    target = tmp_path / "scan.png"
    target.write_bytes(raw)
    roots: list[str] = []

    def _run(paths: list[Path], **kwargs: Any) -> FileModelRun:
        roots.append(str(kwargs["allowed_root"]))
        return _fake_ok(_page_text())(paths, **kwargs)

    monkeypatch.setattr(file_flow_mod, "run_file_model", _run)
    monkeypatch.setattr(cli_mod, "run_model_once", _boom_model)
    out = tmp_path / "out"
    assert main(_args(target, out, _secret(tmp_path))) == 0
    assert target.read_bytes() == raw
    assert roots and all(not Path(root).exists() for root in roots)
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "complete"
    assert result["needsReview"] is True
    assert result["writeEligible"] is False
    assert result["persistence"] == "not-written"
    assert result["model"]["present"] is True
    assert result["source"]["sha256"] == sha
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["sourceSha256"] == sha
    assert provenance["modelPresent"] is True
    assert provenance["transcription"]["method"] == "opencode-native-files"
    assert provenance["transcription"]["untrusted"] is True
    assert (out / "bundle.json").is_file()
    transcript = json.loads((out / "transcription.json").read_text(encoding="utf-8"))
    assert transcript["version"] == 1
    assert transcript["sourceSha256"] == sha
    assert transcript["pages"] == [_page_text()]
    assert transcript["extractSha256"] == provenance["extractSha256"]
    assert stat.S_IMODE(os.stat(out / "transcription.json").st_mode) == 0o600


def test_odd_extension_image_by_magic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "scan.bin"
    target.write_bytes(_png())
    monkeypatch.setattr(file_flow_mod, "run_file_model", _fake_ok(_page_text()))
    monkeypatch.setattr(cli_mod, "run_model_once", _boom_model)
    out = tmp_path / "out"
    assert main(_args(target, out, _secret(tmp_path))) == 0
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "complete"


def test_scanned_pdf_routes_to_file_lane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "scan.pdf"
    target.write_bytes(_minimal_pdf(with_text=False))
    seen: dict[str, Any] = {}

    def _run(paths: list[Path], **kwargs: Any) -> FileModelRun:
        seen["count"] = len(paths)
        seen["suffixes"] = [p.suffix for p in paths]
        seen["root"] = str(kwargs["allowed_root"])
        return _fake_ok(_page_text())(paths, **kwargs)

    monkeypatch.setattr(file_flow_mod, "run_file_model", _run)
    out = tmp_path / "out"
    assert main(_args(target, out, _secret(tmp_path))) == 0
    assert seen["count"] == 1
    assert seen["suffixes"] == [".png"]
    assert not Path(str(seen["root"])).exists()
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "complete"


def test_scanned_pdf_offline_keeps_old_manual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "scan.pdf"
    target.write_bytes(_minimal_pdf(with_text=False))
    monkeypatch.setattr(file_flow_mod, "run_file_model", _boom_model)
    monkeypatch.setattr(cli_mod, "run_model_once", _boom_model)
    out = tmp_path / "out"
    assert main(["--input", str(target), "--output", str(out)]) == 0
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert any(i["code"] == "scan_no_ocr" for i in result["issues"])
    assert not (out / "transcription.json").exists()


def test_blocked_inputs_make_zero_ai_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_flow_mod, "run_file_model", _boom_model)
    monkeypatch.setattr(cli_mod, "run_model_once", _boom_model)
    secret = _secret(tmp_path)
    evil = tmp_path / "evil.jpg"
    evil.write_bytes(b"MZ\x90\x00fake-pe-body")
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"hello not an image")
    real = tmp_path / "real.png"
    real.write_bytes(_png())
    (tmp_path / "link.png").symlink_to(real)
    big = tmp_path / "big.png"
    with open(big, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024))
    cases = [
        (evil, "executable_rejected"),
        (bad, "image_unreadable"),
        (tmp_path / "link.png", "symlink_rejected"),
        (big, "oversized_input"),
    ]
    for target, wanted in cases:
        out = tmp_path / ("out-" + target.name)
        assert main(_args(target, out, secret)) == 2
        result = json.loads((out / "result.json").read_text(encoding="utf-8"))
        assert any(i["code"] == wanted for i in result["issues"])
        assert not (out / "bundle.json").exists()
        assert not (out / "transcription.json").exists()


def test_missing_optin_or_secret_makes_no_ai_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "scan.png"
    target.write_bytes(_png())
    monkeypatch.setattr(file_flow_mod, "run_file_model", _boom_model)
    out = tmp_path / "out-off"
    assert main(["--input", str(target), "--output", str(out)]) == 0
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert any(i["code"] == "azure_not_opted_in" for i in result["issues"])
    assert result["model"]["present"] is False
    out2 = tmp_path / "out-nosecret"
    assert main(["--input", str(target), "--output", str(out2), "--allow-azure"]) == 0
    result2 = json.loads((out2 / "result.json").read_text(encoding="utf-8"))
    assert any(i["code"] == "secret_missing" for i in result2["issues"])
    assert not (out2 / "transcription.json").exists()


def test_invalid_fhir_manual_keeps_draft_and_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "scan.png"
    target.write_bytes(_png())
    monkeypatch.setattr(
        file_flow_mod, "run_file_model", _fake_ok(_page_text(), fhir='{"status": "compl')
    )
    out = tmp_path / "out"
    assert main(_args(target, out, _secret(tmp_path))) == 3
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "manual-review"
    assert result["model"]["present"] is True
    assert not (out / "bundle.json").exists()
    draft = json.loads((out / "model-draft.json").read_text(encoding="utf-8"))
    assert draft["modelOutputText"] == '{"status": "compl'
    transcript = json.loads((out / "transcription.json").read_text(encoding="utf-8"))
    assert transcript["pages"] == [_page_text()]
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["modelPresent"] is True


def test_blank_transcript_manual_retains_raw_with_empty_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "scan.png"
    target.write_bytes(_png())
    blank = json.dumps({"pages": [{"page": 1, "text": "   "}], "issues": []})

    def _run(paths: list[Path], **kwargs: Any) -> FileModelRun:
        sha = hashlib.sha256(target.read_bytes()).hexdigest()
        return FileModelRun(
            raw_fhir=None,
            transcription_raw=blank,
            extracted=None,
            transcription_metadata=_meta(sha, None, 1),
            issue_code="transcript_no_text",
        )

    monkeypatch.setattr(file_flow_mod, "run_file_model", _run)
    out = tmp_path / "out"
    assert main(_args(target, out, _secret(tmp_path))) == 0
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert any(i["code"] == "transcript_no_text" for i in result["issues"])
    draft = json.loads((out / "model-draft.json").read_text(encoding="utf-8"))
    assert draft["candidateText"] == ""
    assert draft["modelOutputText"] == blank
    transcript = json.loads((out / "transcription.json").read_text(encoding="utf-8"))
    assert transcript["pages"] == []
    assert transcript["extractSha256"] is None


def test_identity_conflict_checked_before_fhir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "scan.png"
    target.write_bytes(_png())
    conflict_text = "PAT ZEBRA MRN: AAA GLUCOSE 102 mg/dL MRN: BBB"
    monkeypatch.setattr(file_flow_mod, "run_file_model", _fake_ok(conflict_text))
    out = tmp_path / "out"
    assert main(_args(target, out, _secret(tmp_path))) == 0
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert any(i["code"] == "conflicting_identity" for i in result["issues"])
    assert not (out / "bundle.json").exists()
    assert (out / "transcription.json").is_file()


def test_text_flow_still_uses_text_extractor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "doc.txt"
    target.write_text("PAT ZEBRA SYN-000001 GLUCOSE 102 mg/dL", encoding="utf-8")

    def _fake(*args: Any, **kwargs: Any) -> str:
        assert "PAT ZEBRA" in str(args[0])
        return _mock_complete()

    monkeypatch.setattr(cli_mod, "run_model_once", _fake)
    monkeypatch.setattr(file_flow_mod, "run_file_model", _boom_model)
    out = tmp_path / "out"
    assert main(_args(target, out, _secret(tmp_path))) == 0
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "complete"
    assert not (out / "transcription.json").exists()


def test_image_check_and_extract_need_no_ai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "scan.png"
    target.write_bytes(_png())
    monkeypatch.setattr(file_flow_mod, "run_file_model", _boom_model)
    monkeypatch.setattr(cli_mod, "run_model_once", _boom_model)
    assert main(["--input", str(target), "--output", str(tmp_path / "o1"), "--check"]) == 2
    out = tmp_path / "o2"
    assert main(["--input", str(target), "--output", str(out), "--extract"]) == 0
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert any(i["code"] == "image_no_ocr" for i in result["issues"])
