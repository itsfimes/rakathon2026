from __future__ import annotations

import asyncio
import contextlib
import hashlib
import math
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rakathon_backend.b5.opencode.file_client import (
    FILE_ALLOWED_ROOT,
    MAX_FILE_BYTES,
    OpenCodeFileClient,
)
from rakathon_backend.b5.opencode.process import OpenCodeProcess
from rakathon_backend.b5.opencode.validation import (
    AZURE_BASE_URL,
    AZURE_PROVIDER_ID,
    EXPECTED_VERSION,
    MAX_RESPONSE_BYTES,
)
from rakathon_backend.common.errors import TransportError
from rakathon_backend.converter.agent import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER_ID,
    INFERENCE_TIMEOUT,
    STARTUP_TIMEOUT,
    TOTAL_TIMEOUT,
    AgentError,
)
from rakathon_backend.converter.detect import suffix_is_executable
from rakathon_backend.converter.extract import Extracted, sniff_executable
from rakathon_backend.converter.prompt import build_prompt
from rakathon_backend.converter.transcription import (
    TranscriptionError,
    build_extracted,
    build_transcription_prompt,
    parse_transcription,
)

FILE_RUN_BINARY = "opencode"
FILE_RUN_PROVIDER_KIND = "azure"
MAX_FHIR_BYTES = MAX_RESPONSE_BYTES


@dataclass(frozen=True, slots=True)
class FileModelRun:
    raw_fhir: str | None
    transcription_raw: str | None
    extracted: Extracted | None
    transcription_metadata: dict[str, Any]
    issue_code: str | None


@dataclass(slots=True)
class _Accumulator:
    transcription_raw: str | None = None
    extracted: Extracted | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _emit_progress(callback: Callable[[str], None] | None, code: str) -> None:
    if callback is None:
        return
    with contextlib.suppress(Exception):
        callback(code)


def _error_partial(exc: BaseException) -> str | None:
    value: Any = getattr(exc, "partial_text", None)
    if not isinstance(value, str) or not value.strip():
        return None
    encoded = value.encode("utf-8")
    if len(encoded) > MAX_RESPONSE_BYTES:
        encoded = encoded[:MAX_RESPONSE_BYTES]
    text = encoded.decode("utf-8", "ignore")
    return text if text.strip() else None


def _check_timeouts(startup_timeout: float, inference_timeout: float, total_timeout: float) -> None:
    for value in (startup_timeout, inference_timeout, total_timeout):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise AgentError("bad_timeout", "timeout budget is outside the limit")
    if not math.isfinite(startup_timeout) or not 0 < startup_timeout <= STARTUP_TIMEOUT:
        raise AgentError("bad_timeout", "timeout budget is outside the limit")
    if not math.isfinite(inference_timeout) or not 0 < inference_timeout <= TOTAL_TIMEOUT:
        raise AgentError("bad_timeout", "timeout budget is outside the limit")
    if not math.isfinite(total_timeout) or not 0 < total_timeout <= TOTAL_TIMEOUT:
        raise AgentError("bad_timeout", "timeout budget is outside the limit")


def _validate_original(original: Path, expected_sha256: str | None) -> tuple[bytes, str, str, str]:
    if original.is_symlink():
        raise AgentError("symlink_rejected", "input path is a symlink")
    try:
        info = original.stat()
    except OSError as exc:
        raise AgentError("unreadable_input", "input file cannot be read") from exc
    if not stat.S_ISREG(info.st_mode):
        raise AgentError("special_file_rejected", "input is not a regular file")
    if info.st_size > MAX_FILE_BYTES:
        raise AgentError("oversized_input", "input exceeds the raw size cap")
    if info.st_size == 0:
        raise AgentError("empty_input", "input file is empty")
    suffix = original.suffix.lower()
    if suffix_is_executable(suffix):
        raise AgentError("executable_rejected", "executable input is rejected")
    try:
        raw = original.read_bytes()
    except OSError as exc:
        raise AgentError("unreadable_input", "input file cannot be read") from exc
    if len(raw) > MAX_FILE_BYTES:
        raise AgentError("oversized_input", "input exceeds the raw size cap")
    if not raw:
        raise AgentError("empty_input", "input file is empty")
    if sniff_executable(raw):
        raise AgentError("executable_rejected", "executable input is rejected")
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and expected_sha256.strip().lower() != digest:
        raise AgentError("source_mismatch", "input digest does not match the expected value")
    return (raw, digest, suffix, original.name)


def _partial(acc: _Accumulator, raw_fhir: str | None, issue_code: str) -> FileModelRun:
    return FileModelRun(
        raw_fhir=raw_fhir,
        transcription_raw=acc.transcription_raw,
        extracted=acc.extracted,
        transcription_metadata=dict(acc.metadata),
        issue_code=issue_code,
    )


async def _two_turn(
    prepared: list[Path],
    *,
    source_sha256: str,
    suffix: str,
    filename: str,
    allowed_root: Path,
    provider_id: str,
    model: str,
    api_key: str,
    startup_timeout: float,
    inference_timeout: float,
    total_timeout: float,
    on_progress: Callable[[str], None] | None,
) -> FileModelRun:
    acc = _Accumulator()
    acc.metadata = {
        "method": "opencode-native-files",
        "untrusted": True,
        "source_sha256": source_sha256,
        "extract_sha256": None,
        "page_count": len(prepared),
        "issues": [],
        "model": provider_id.strip() + "/" + model.strip(),
    }

    async def _body() -> FileModelRun:
        process = OpenCodeProcess(
            FILE_RUN_BINARY,
            EXPECTED_VERSION,
            provider_id,
            model,
            AZURE_BASE_URL,
            startup_timeout=startup_timeout,
            api_key=api_key,
            provider_kind=FILE_RUN_PROVIDER_KIND,
            file_mode=True,
        )
        client: OpenCodeFileClient | None = None
        session_id = ""
        try:
            _emit_progress(on_progress, "file_read_start")
            try:
                base_url = await process.start()
            except TransportError as exc:
                raise AgentError("process_failed", "converter file process failed") from exc
            _, password = process.auth()
            current = OpenCodeFileClient(
                base_url,
                password,
                provider_id,
                model,
                timeout=inference_timeout,
                allowed_root=allowed_root,
            )
            client = current
            try:
                session_id = await current.create_session()
            except TransportError as exc:
                raise AgentError("session_failed", "converter file session failed") from exc
            prompt = build_transcription_prompt(len(prepared))
            turn_ok = True
            try:
                first = await current.prompt_files(session_id, prompt, prepared)
                raw_text = first.text
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await asyncio.shield(current.interrupt(session_id))
                raise
            except TransportError as exc:
                draft = _error_partial(exc)
                if draft is None:
                    raise AgentError("inference_failed", "converter transcription failed") from exc
                raw_text = draft
                turn_ok = False
            acc.transcription_raw = raw_text
            _emit_progress(on_progress, "transcription_done")
            try:
                parsed = parse_transcription(raw_text, page_count=len(prepared))
                extracted = build_extracted(
                    parsed.pages,
                    source_sha256=source_sha256,
                    suffix=suffix,
                    filename=filename,
                )
            except TranscriptionError as exc:
                return _partial(acc, None, exc.code)
            acc.extracted = extracted
            acc.metadata["extract_sha256"] = extracted.extract_sha256
            acc.metadata["issues"] = list(parsed.issues)
            if not turn_ok:
                return _partial(acc, None, "transcript_failed")
            _emit_progress(on_progress, "fhir_start")
            try:
                fhir_prompt = build_prompt(extracted)
            except ValueError:
                return _partial(acc, None, "fhir_failed")
            try:
                second = await current.prompt_text(session_id, fhir_prompt)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await asyncio.shield(current.interrupt(session_id))
                raise
            except TransportError as exc:
                return _partial(acc, _error_partial(exc), "fhir_failed")
            fhir_text = second.text
            if len(fhir_text.encode("utf-8")) > MAX_FHIR_BYTES:
                return _partial(acc, None, "fhir_too_large")
            return FileModelRun(
                raw_fhir=fhir_text,
                transcription_raw=raw_text,
                extracted=extracted,
                transcription_metadata=dict(acc.metadata),
                issue_code=None,
            )
        finally:
            if client is not None and session_id:
                with contextlib.suppress(Exception):
                    await asyncio.shield(client.delete(session_id))
            if client is not None:
                with contextlib.suppress(Exception):
                    await asyncio.shield(client.aclose())
            with contextlib.suppress(Exception):
                await asyncio.shield(process.close())

    try:
        return await asyncio.wait_for(_body(), total_timeout)
    except TimeoutError as exc:
        if acc.transcription_raw is not None:
            return _partial(acc, None, "agent_timeout")
        raise AgentError("agent_timeout", "converter file run exceeded its budget") from exc


def run_file_model(
    input_paths: list[Path],
    *,
    original_path: Path,
    allowed_root: Path = Path(FILE_ALLOWED_ROOT),
    provider_id: str = DEFAULT_PROVIDER_ID,
    model: str = DEFAULT_MODEL,
    base_url: str = AZURE_BASE_URL,
    api_key: str,
    expected_sha256: str | None = None,
    startup_timeout: float = STARTUP_TIMEOUT,
    inference_timeout: float = INFERENCE_TIMEOUT,
    total_timeout: float = TOTAL_TIMEOUT,
    on_progress: Callable[[str], None] | None = None,
) -> FileModelRun:
    if not api_key or not api_key.strip():
        raise AgentError("secret_missing", "api key is required for the azure call")
    if provider_id.strip() != AZURE_PROVIDER_ID:
        raise AgentError("untrusted_endpoint", "only the trusted azure endpoint is allowed")
    if base_url.strip().rstrip("/") != AZURE_BASE_URL:
        raise AgentError("untrusted_endpoint", "only the trusted azure endpoint is allowed")
    _check_timeouts(startup_timeout, inference_timeout, total_timeout)
    if not input_paths:
        raise AgentError("input_missing", "no prepared input files were provided")
    prepared = list(input_paths)
    _, source_sha256, suffix, filename = _validate_original(original_path, expected_sha256)

    async def _main() -> FileModelRun:
        return await _two_turn(
            prepared,
            source_sha256=source_sha256,
            suffix=suffix,
            filename=filename,
            allowed_root=allowed_root,
            provider_id=provider_id,
            model=model,
            api_key=api_key,
            startup_timeout=startup_timeout,
            inference_timeout=inference_timeout,
            total_timeout=total_timeout,
            on_progress=on_progress,
        )

    try:
        return asyncio.run(_main())
    except AgentError:
        raise
    except (OSError, RuntimeError) as exc:
        raise AgentError("agent_failed", "converter file run failed") from exc
