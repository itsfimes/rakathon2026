from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.b5.opencode.file_client import FilePromptResult
from rakathon_backend.common.errors import TransportError
from rakathon_backend.converter import file_agent
from rakathon_backend.converter.agent import AgentError
from rakathon_backend.converter.file_agent import FileModelRun, run_file_model
from rakathon_backend.converter.prompt import build_prompt
from rakathon_backend.converter.transcription import build_extracted

PROCESSES: list[Any] = []
CLIENTS: list[Any] = []
SCRIPT: dict[str, Any] = {}
ORIGINAL_BYTES = b"original-bytes-fixture"
SECOND_TEXT = '{"status": "complete", "bundle": null}'


class _PartialError(TransportError):
    partial_text: str

    def __init__(self, partial: str) -> None:
        super().__init__(code="ai_bad_output", message="assistant finish was not stop")
        self.partial_text = partial


class FakeProcess:
    def __init__(
        self,
        binary: str,
        expected: str,
        provider_id: str,
        model: str,
        base_url: str,
        *,
        startup_timeout: float,
        api_key: str = "",
        provider_kind: str = "local",
        file_mode: bool = False,
    ) -> None:
        self.calls: list[str] = []
        self.file_mode = file_mode
        self.provider_id = provider_id
        self.model = model
        PROCESSES.append(self)

    async def start(self) -> str:
        self.calls.append("start")
        return "http://127.0.0.1:4311"

    def auth(self) -> tuple[str, str]:
        return ("opencode", "pw-value")

    async def close(self) -> None:
        self.calls.append("close")


class FakeClient:
    def __init__(
        self,
        base_url: str,
        password: str,
        provider_id: str,
        model: str,
        *,
        timeout: float,
        max_response_bytes: int = 262144,
        transport: Any = None,
        allowed_root: str | Path = "/input",
    ) -> None:
        self.calls: list[tuple[Any, ...]] = []
        CLIENTS.append(self)

    async def create_session(self) -> str:
        self.calls.append(("create",))
        return str(SCRIPT.get("session_id", "ses-1"))

    async def prompt_files(self, session_id: str, text: str, paths: list[Path]) -> FilePromptResult:
        self.calls.append(("files", session_id, text, list(paths)))
        mode = SCRIPT.get("first_mode", "ok")
        if mode == "error":
            raise TransportError(code="ai_transport", message="opencode transport failed")
        if mode == "partial":
            raise _PartialError(str(SCRIPT.get("first_partial", "")))
        return FilePromptResult(
            text=str(SCRIPT["first_text"]), assistant_id="a-1", admission_id="u-1"
        )

    async def prompt_text(self, session_id: str, text: str) -> FilePromptResult:
        self.calls.append(("text", session_id, text))
        mode = SCRIPT.get("second_mode", "ok")
        if mode == "error":
            raise TransportError(code="ai_transport", message="opencode transport failed")
        if mode == "partial":
            raise _PartialError(str(SCRIPT.get("second_partial", "")))
        if mode == "cancel":
            raise asyncio.CancelledError
        if mode == "sleep":
            await asyncio.sleep(30.0)
        return FilePromptResult(
            text=str(SCRIPT["second_text"]), assistant_id="a-2", admission_id="u-2"
        )

    async def interrupt(self, session_id: str) -> None:
        self.calls.append(("interrupt", session_id))

    async def delete(self, session_id: str) -> None:
        self.calls.append(("delete", session_id))

    async def aclose(self) -> None:
        self.calls.append(("close",))


@pytest.fixture()
def _wired(monkeypatch: pytest.MonkeyPatch) -> None:
    PROCESSES.clear()
    CLIENTS.clear()
    SCRIPT.clear()
    SCRIPT["second_text"] = SECOND_TEXT
    monkeypatch.setattr(file_agent, "OpenCodeProcess", FakeProcess)
    monkeypatch.setattr(file_agent, "OpenCodeFileClient", FakeClient)


def _write(target: Path, data: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _valid_transcript() -> str:
    return json.dumps({"pages": [{"page": 1, "text": "Glucose 5.6 mmol/L"}], "issues": []})


def _run(tmp_path: Path, transcript: str | None = None, **kwargs: Any) -> FileModelRun:
    original = _write(tmp_path / "case" / "report.pdf", ORIGINAL_BYTES)
    preview = _write(tmp_path / "prep" / "p1.png", b"preview-pixels-differ")
    if transcript is not None:
        SCRIPT["first_text"] = transcript
    params: dict[str, Any] = {"original_path": original, "api_key": "secret-key"}
    params.update(kwargs)
    return run_file_model([preview], **params)


def test_success_two_ordered_turns(tmp_path: Path, _wired: None) -> None:
    seen: list[str] = []
    transcript = _valid_transcript()
    result = _run(tmp_path, transcript, on_progress=seen.append)
    digest = hashlib.sha256(ORIGINAL_BYTES).hexdigest()
    assert result.issue_code is None
    assert result.transcription_raw == transcript
    assert result.raw_fhir == SECOND_TEXT
    assert result.extracted is not None
    assert result.extracted.pages == ("Glucose 5.6 mmol/L",)
    assert result.extracted.text == "[page 1]\nGlucose 5.6 mmol/L"
    assert result.extracted.source_sha256 == digest
    assert result.extracted.suffix == ".pdf"
    assert result.extracted.filename == "report.pdf"
    assert result.transcription_metadata["method"] == "opencode-native-files"
    assert result.transcription_metadata["untrusted"] is True
    assert result.transcription_metadata["source_sha256"] == digest
    assert seen == ["file_read_start", "transcription_done", "fhir_start"]
    assert len(PROCESSES) == 1 and PROCESSES[0].file_mode is True
    assert len(CLIENTS) == 1
    calls = CLIENTS[0].calls
    assert [entry[0] for entry in calls] == ["create", "files", "text", "delete", "close"]
    assert calls[1][1] == "ses-1"
    assert calls[2][1] == "ses-1"
    expected = build_extracted(
        ("Glucose 5.6 mmol/L",),
        source_sha256=digest,
        suffix=".pdf",
        filename="report.pdf",
    )
    assert calls[2][2] == build_prompt(expected)


def test_bad_transcription_keeps_raw_without_second(tmp_path: Path, _wired: None) -> None:
    result = _run(tmp_path, "not json")
    assert result.issue_code == "transcript_bad_json"
    assert result.transcription_raw == "not json"
    assert result.extracted is None
    assert result.raw_fhir is None
    assert [entry[0] for entry in CLIENTS[0].calls] == ["create", "files", "delete", "close"]


def test_blank_transcription_skips_fhir(tmp_path: Path, _wired: None) -> None:
    raw = json.dumps({"pages": [{"page": 1, "text": "   "}], "issues": ["blank_page"]})
    result = _run(tmp_path, raw)
    assert result.issue_code == "transcript_no_text"
    assert result.transcription_raw == raw
    assert result.extracted is None
    assert [entry[0] for entry in CLIENTS[0].calls] == ["create", "files", "delete", "close"]


def test_first_error_partial_draft_retained(tmp_path: Path, _wired: None) -> None:
    SCRIPT["first_mode"] = "partial"
    SCRIPT["first_partial"] = '{"pages": [{"page": 1'
    result = _run(tmp_path)
    assert result.issue_code == "transcript_bad_json"
    assert result.transcription_raw == '{"pages": [{"page": 1'
    assert result.extracted is None
    assert [entry[0] for entry in CLIENTS[0].calls] == ["create", "files", "delete", "close"]


def test_second_failure_keeps_partial(tmp_path: Path, _wired: None) -> None:
    SCRIPT["second_mode"] = "error"
    transcript = _valid_transcript()
    result = _run(tmp_path, transcript)
    assert result.issue_code == "fhir_failed"
    assert result.raw_fhir is None
    assert result.transcription_raw == transcript
    assert result.extracted is not None
    assert result.extracted.pages == ("Glucose 5.6 mmol/L",)


def test_second_partial_preserved_as_draft(tmp_path: Path, _wired: None) -> None:
    SCRIPT["second_mode"] = "partial"
    SCRIPT["second_partial"] = '{"status": "incomplete"'
    result = _run(tmp_path, _valid_transcript())
    assert result.issue_code == "fhir_failed"
    assert result.raw_fhir == '{"status": "incomplete"'
    assert result.transcription_raw == _valid_transcript()


def test_timeout_keeps_partial_and_cleans(tmp_path: Path, _wired: None) -> None:
    SCRIPT["second_mode"] = "sleep"
    transcript = _valid_transcript()
    original = _write(tmp_path / "case" / "report.pdf", ORIGINAL_BYTES)
    preview = _write(tmp_path / "prep" / "p1.png", b"preview-pixels-differ")
    SCRIPT["first_text"] = transcript
    result = run_file_model(
        [preview],
        original_path=original,
        api_key="secret-key",
        total_timeout=0.2,
    )
    assert result.issue_code == "agent_timeout"
    assert result.transcription_raw == transcript
    assert result.extracted is not None
    kinds = [entry[0] for entry in CLIENTS[0].calls]
    assert "interrupt" in kinds and "delete" in kinds and "close" in kinds
    assert PROCESSES[0].calls.count("close") == 1


def test_cancel_interrupts_and_cleans(tmp_path: Path, _wired: None) -> None:
    SCRIPT["second_mode"] = "cancel"
    with pytest.raises(asyncio.CancelledError):
        _run(tmp_path, _valid_transcript())
    kinds = [entry[0] for entry in CLIENTS[0].calls]
    assert "interrupt" in kinds and "delete" in kinds and "close" in kinds
    assert PROCESSES[0].calls.count("close") == 1


@pytest.mark.parametrize("kind", ["missing", "symlink", "empty", "executable", "magic"])
def test_invalid_original_zero_api(tmp_path: Path, _wired: None, kind: str) -> None:
    target = tmp_path / "case" / "report.pdf"
    if kind == "missing":
        target.parent.mkdir(parents=True, exist_ok=True)
    elif kind == "symlink":
        real = _write(tmp_path / "real.pdf", ORIGINAL_BYTES)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(real)
    elif kind == "empty":
        _write(target, b"")
    elif kind == "executable":
        _write(tmp_path / "case" / "tool.exe", b"content-bytes")
        target = tmp_path / "case" / "tool.exe"
    else:
        _write(target, b"\x7fELF" + b"0" * 64)
    preview = _write(tmp_path / "prep" / "p1.png", b"preview")
    with pytest.raises(AgentError):
        run_file_model([preview], original_path=target, api_key="secret-key")
    assert PROCESSES == [] and CLIENTS == []


def test_secret_and_endpoint_fail_without_api(tmp_path: Path, _wired: None) -> None:
    original = _write(tmp_path / "case" / "report.pdf", ORIGINAL_BYTES)
    preview = _write(tmp_path / "prep" / "p1.png", b"preview")
    with pytest.raises(AgentError):
        run_file_model([preview], original_path=original, api_key="")
    with pytest.raises(AgentError):
        run_file_model([preview], original_path=original, api_key="   ")
    with pytest.raises(AgentError):
        run_file_model(
            [preview],
            original_path=original,
            api_key="secret-key",
            base_url="https://untrusted.example/v1",
        )
    with pytest.raises(AgentError):
        run_file_model([], original_path=original, api_key="secret-key")
    assert PROCESSES == [] and CLIENTS == []


def test_expected_sha_mismatch_without_api(tmp_path: Path, _wired: None) -> None:
    original = _write(tmp_path / "case" / "report.pdf", ORIGINAL_BYTES)
    preview = _write(tmp_path / "prep" / "p1.png", b"preview")
    with pytest.raises(AgentError):
        run_file_model(
            [preview],
            original_path=original,
            api_key="secret-key",
            expected_sha256="0" * 64,
        )
    assert PROCESSES == [] and CLIENTS == []
    digest = hashlib.sha256(ORIGINAL_BYTES).hexdigest()
    SCRIPT["first_text"] = _valid_transcript()
    result = run_file_model(
        [preview], original_path=original, api_key="secret-key", expected_sha256=digest
    )
    assert result.issue_code is None
