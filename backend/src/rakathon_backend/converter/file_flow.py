from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from rakathon_backend.converter.agent import AgentError, read_secret_file
from rakathon_backend.converter.cli_progress import report_stored as _report_stored
from rakathon_backend.converter.cli_progress import write_progress as _write_progress
from rakathon_backend.converter.extract import (
    Extracted,
    detect_identity_conflict,
    hash_only,
)
from rakathon_backend.converter.file_agent import FileModelRun, run_file_model
from rakathon_backend.converter.file_inputs import (
    FileInputError,
    PreparedFileInput,
    prepare_file_inputs,
)
from rakathon_backend.converter.model_draft import (
    MAX_MODEL_OUTPUT_BYTES,
    MODEL_DRAFT_VERSION,
    build_model_draft,
)
from rakathon_backend.converter.output import (
    OutputError,
    assemble_result,
    check_evidence,
    manual_result,
    parse_model_output_strict,
)
from rakathon_backend.converter.output_io import (
    _atomic_write,
    write_model_draft,
    write_outputs,
)
from rakathon_backend.converter.transcription import TRANSCRIPT_MAX_BYTES

EXIT_OK = 0
EXIT_REJECTED = 2
EXIT_MODEL_FAILED = 3
TRANSCRIPTION_FILENAME = "transcription.json"
TRANSCRIPTION_VERSION = 1


def _progress(args: argparse.Namespace, code: str) -> None:
    _write_progress(args, code, {"newFormat": False, "recipeReuse": False, "attempts": []})


def _truncate(text: str, cap: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= cap:
        return text
    return raw[:cap].decode("utf-8", "ignore")


def _transcription_doc(run: FileModelRun, source_sha: str) -> dict[str, Any] | None:
    raw = run.transcription_raw
    if raw is None or not raw.strip():
        return None
    pages: list[str] = []
    extract_sha: Any = run.transcription_metadata.get("extract_sha256")
    if run.extracted is not None:
        pages = list(run.extracted.pages)
        extract_sha = run.extracted.extract_sha256
    return {
        "version": TRANSCRIPTION_VERSION,
        "sourceSha256": source_sha,
        "untrusted": True,
        "method": "opencode-native-files",
        "modelOutputText": _truncate(raw, TRANSCRIPT_MAX_BYTES),
        "pages": pages,
        "extractSha256": extract_sha if isinstance(extract_sha, str) else None,
    }


def _draft_for(
    run: FileModelRun, source_sha: str, provider_id: str, model: str
) -> dict[str, Any] | None:
    fhir = run.raw_fhir
    if fhir is not None and fhir.strip():
        return build_model_draft(fhir, source_sha, provider_id, model)
    raw = run.transcription_raw
    if raw is not None and raw.strip():
        return {
            "version": MODEL_DRAFT_VERSION,
            "sourceSha256": source_sha,
            "modelOutputText": _truncate(raw, MAX_MODEL_OUTPUT_BYTES),
            "candidateText": "",
            "model": {"providerId": provider_id, "model": model},
        }
    return None


def _write_transcription(outdir: Path, doc: dict[str, Any]) -> None:
    if outdir.is_symlink():
        raise OutputError("output_symlink", "output directory is a symlink")
    if not outdir.is_dir():
        raise OutputError("output_not_dir", "output path is not a directory")
    _atomic_write(outdir / TRANSCRIPTION_FILENAME, json.dumps(doc, indent=2).encode())


def _write_after(
    outdir: Path, draft: dict[str, Any] | None, transcription: dict[str, Any] | None
) -> None:
    if draft is not None:
        try:
            write_model_draft(outdir, draft)
        except (OutputError, OSError):
            return
    if transcription is not None:
        try:
            _write_transcription(outdir, transcription)
        except (OutputError, OSError):
            return


def _result_marker(
    result: dict[str, Any], provenance: dict[str, Any], metadata: dict[str, Any] | None
) -> None:
    if metadata is None:
        return
    provenance["transcription"] = dict(metadata)
    extract_sha = metadata.get("extract_sha256")
    result["transcription"] = {
        "method": str(metadata.get("method", "opencode-native-files")),
        "untrusted": True,
        "pages": int(metadata.get("page_count", 0)),
        "extractSha256": extract_sha if isinstance(extract_sha, str) else None,
    }


def _mark_present(result: dict[str, Any], provenance: dict[str, Any]) -> None:
    model = result.get("model")
    if isinstance(model, dict):
        model["present"] = True
    provenance["modelPresent"] = True


def _file_manual(
    args: argparse.Namespace,
    started: float,
    code: str,
    message: str,
    extracted: Extracted | None,
    metadata: dict[str, Any] | None,
    draft: dict[str, Any] | None,
    transcription: dict[str, Any] | None,
    present: bool = False,
    exit_code: int = EXIT_OK,
) -> int:
    runtime_s = time.monotonic() - started
    filename: str | None = None
    source_sha: str | None = None
    if extracted is None:
        hashed = hash_only(str(args.input))
        if hashed is not None:
            source_sha, filename = hashed
    result, bundle, provenance = manual_result(
        code,
        message,
        extracted,
        provider_id=str(args.provider_id),
        model=str(args.model),
        runtime_s=runtime_s,
        filename=filename,
        source_sha=source_sha,
    )
    _result_marker(result, provenance, metadata)
    if present:
        _mark_present(result, provenance)
    try:
        write_outputs(Path(str(args.output)), result, bundle, provenance)
    except OutputError as exc:
        sys.stderr.write(json.dumps({"error": exc.code}) + "\n")
        return EXIT_REJECTED
    _write_after(Path(str(args.output)), draft, transcription)
    _report_stored(result, runtime_s)
    return exit_code


def _finish_run(
    args: argparse.Namespace,
    started: float,
    prep: PreparedFileInput,
    run: FileModelRun,
    provider_id: str,
    model: str,
) -> int:
    sha = prep.source_sha256
    metadata = dict(run.transcription_metadata)
    metadata.update(source_sha256=sha, untrusted=True)
    if prep.animated:
        metadata["firstFrameOnly"] = True
    transcription = _transcription_doc(run, sha)
    draft = _draft_for(run, sha, provider_id, model)
    present = bool(run.transcription_raw is not None and run.transcription_raw.strip())
    extracted = run.extracted
    if run.issue_code is not None:
        return _file_manual(
            args,
            started,
            run.issue_code,
            "native file " + run.issue_code + " needs human review",
            extracted,
            metadata,
            draft,
            transcription,
            present,
        )
    if extracted is None:
        return _file_manual(
            args,
            started,
            "transcript_failed",
            "native file transcript_failed needs human review",
            None,
            metadata,
            draft,
            transcription,
            present,
        )
    conflict, _ = detect_identity_conflict(extracted.text)
    if conflict:
        return _file_manual(
            args,
            started,
            "conflicting_identity",
            "pages carry conflicting ids",
            extracted,
            metadata,
            draft,
            transcription,
            present,
        )
    raw_fhir = run.raw_fhir or ""
    if not raw_fhir.strip():
        return _file_manual(
            args,
            started,
            "fhir_failed",
            "native file fhir_failed needs human review",
            extracted,
            metadata,
            draft,
            transcription,
            present,
        )
    try:
        parsed = parse_model_output_strict(raw_fhir)
        checked = check_evidence(parsed, extracted, conflict=False)
    except OutputError as exc:
        return _file_manual(
            args,
            started,
            exc.code,
            exc.message,
            extracted,
            metadata,
            draft,
            transcription,
            present,
            EXIT_MODEL_FAILED,
        )
    runtime_s = time.monotonic() - started
    result, bundle, provenance = assemble_result(
        checked,
        extracted,
        model_present=True,
        provider_id=provider_id,
        model=model,
        runtime_s=runtime_s,
    )
    _result_marker(result, provenance, metadata)
    try:
        write_outputs(Path(str(args.output)), result, bundle, provenance)
    except OutputError as exc:
        sys.stderr.write(json.dumps({"error": exc.code}) + "\n")
        return EXIT_MODEL_FAILED
    _write_after(Path(str(args.output)), draft, transcription)
    _report_stored(result, runtime_s)
    return EXIT_OK


def run_file_flow(args: argparse.Namespace, started: float) -> int:
    provider_id = str(args.provider_id)
    model = str(args.model)
    if not args.allow_azure:
        return _file_manual(
            args,
            started,
            "azure_not_opted_in",
            "azure inference needs --allow-azure plus a secret",
            None,
            None,
            None,
            None,
        )
    if not args.secret_file:
        return _file_manual(
            args,
            started,
            "secret_missing",
            "azure inference needs --secret-file",
            None,
            None,
            None,
            None,
        )
    try:
        api_key = read_secret_file(str(args.secret_file))
    except AgentError as exc:
        return _file_manual(args, started, exc.code, exc.message, None, None, None, None)
    try:
        with prepare_file_inputs(str(args.input)) as prep:
            _progress(args, "file_read_start")
            try:
                run = run_file_model(
                    list(prep.staged),
                    original_path=prep.original,
                    allowed_root=prep.root,
                    provider_id=provider_id,
                    model=model,
                    base_url=str(args.base_url),
                    api_key=api_key,
                    startup_timeout=float(args.startup_timeout),
                    inference_timeout=float(args.inference_timeout),
                    total_timeout=float(args.total_timeout),
                    on_progress=lambda code: _progress(args, code),
                )
            except AgentError as exc:
                return _file_manual(args, started, exc.code, exc.message, None, None, None, None)
            return _finish_run(args, started, prep, run, provider_id, model)
    except FileInputError as exc:
        return _file_manual(
            args,
            started,
            exc.code,
            exc.message,
            None,
            None,
            None,
            None,
            False,
            EXIT_OK if exc.manual else EXIT_REJECTED,
        )
