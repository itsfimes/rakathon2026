from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rakathon_backend.converter.agent import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER_ID,
    AgentError,
    read_secret_file,
    run_model_once,
)
from rakathon_backend.converter.cli_progress import (
    report_stored as _report_stored,
)
from rakathon_backend.converter.cli_progress import (
    report_summary as _summary,
)
from rakathon_backend.converter.cli_progress import (
    write_progress as _write_progress,
)
from rakathon_backend.converter.extract import (
    ConverterError,
    Extracted,
    ManualReviewNeeded,
    detect_identity_conflict,
    extract_file,
    hash_only,
)
from rakathon_backend.converter.file_flow import run_file_flow
from rakathon_backend.converter.file_inputs import needs_file_lane
from rakathon_backend.converter.model_draft import build_model_draft
from rakathon_backend.converter.output import (
    OutputError,
    assemble_result,
    check_evidence,
    manual_result,
    parse_model_output_strict,
    write_outputs,
)
from rakathon_backend.converter.output_io import write_model_draft
from rakathon_backend.converter.planner import RecipeCache, parse_recipe_strict
from rakathon_backend.converter.prompt import build_prompt
from rakathon_backend.converter.unknown import (
    attach_adaptive as _attach_adaptive,
)
from rakathon_backend.converter.unknown import clear_last_adaptive as _clear_last
from rakathon_backend.converter.unknown import last_adaptive as _last_info
from rakathon_backend.converter.unknown import read_raw_for_unknown as _read_raw_for_unknown
from rakathon_backend.converter.unknown import unknown_flow as _unknown_flow

EXIT_OK = 0
EXIT_REJECTED = 2
EXIT_MODEL_FAILED = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rakathon-converter")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--secret-file", default=None)
    parser.add_argument("--allow-azure", action="store_true")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--provider-id", default=DEFAULT_PROVIDER_ID)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    parser.add_argument("--inference-timeout", type=float, default=180.0)
    parser.add_argument("--total-timeout", type=float, default=240.0)
    return parser


def _retain_draft(outdir: Path, draft: dict[str, Any] | None) -> None:
    if draft is None:
        return
    try:
        write_model_draft(outdir, draft)
    except (OutputError, OSError):
        return


def _manual_exit(
    args: argparse.Namespace,
    code: str,
    message: str,
    extracted: Extracted | None,
    started: float,
    exit_code: int,
    draft: dict[str, Any] | None = None,
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
    if _last_info().get("newFormat") is True:
        _attach_adaptive(result, provenance, _last_info())
    try:
        write_outputs(Path(str(args.output)), result, bundle, provenance)
    except OutputError as exc:
        sys.stderr.write(json.dumps({"error": exc.code}) + "\n")
        return EXIT_REJECTED
    _retain_draft(Path(str(args.output)), draft)
    _report_stored(result, runtime_s)
    return exit_code


def _extract_only(args: argparse.Namespace, started: float) -> int:
    try:
        extracted = extract_file(str(args.input))
    except ManualReviewNeeded as exc:
        return _manual_exit(args, exc.code, exc.message, None, started, EXIT_OK)
    except ConverterError as exc:
        return _manual_exit(args, exc.code, exc.message, None, started, EXIT_REJECTED)
    outdir = Path(str(args.output))
    if outdir.is_symlink():
        sys.stderr.write(json.dumps({"error": "output_symlink"}) + "\n")
        return EXIT_REJECTED
    if outdir.exists():
        if not outdir.is_dir():
            sys.stderr.write(json.dumps({"error": "output_not_dir"}) + "\n")
            return EXIT_REJECTED
        try:
            if any(outdir.iterdir()):
                sys.stderr.write(json.dumps({"error": "output_exists"}) + "\n")
                return EXIT_REJECTED
        except OSError:
            sys.stderr.write(json.dumps({"error": "output_unreadable"}) + "\n")
            return EXIT_REJECTED
    else:
        try:
            outdir.mkdir(parents=True, mode=0o700)
        except OSError:
            sys.stderr.write(json.dumps({"error": "output_mkdir"}) + "\n")
            return EXIT_REJECTED
    try:
        extract_path = outdir / "extract.txt"
        provenance_path = outdir / "provenance.json"
        extract_path.write_text(extracted.text, encoding="utf-8")
        provenance_path.write_text(
            json.dumps(
                {
                    "sourceSha256": extracted.source_sha256,
                    "extractSha256": extracted.extract_sha256,
                    "pages": len(extracted.pages),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        os.chmod(extract_path, 0o600)
        os.chmod(provenance_path, 0o600)
    except OSError:
        sys.stderr.write(json.dumps({"error": "output_write"}) + "\n")
        return EXIT_REJECTED
    _summary("extracted", {}, False, time.monotonic() - started)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _main(argv)
    except (OSError, ValueError, AgentError) as exc:
        code = getattr(exc, "code", "internal_error")
        sys.stderr.write(json.dumps({"error": str(code)}) + "\n")
        return EXIT_REJECTED


def _commit_recipe_if_validated(adaptive_info: dict[str, Any], status: str) -> None:
    if status != "complete":
        return
    pending = adaptive_info.get("pendingRecipe")
    if not isinstance(pending, dict):
        return
    fingerprint = str(adaptive_info.get("fingerprint", ""))
    if not fingerprint:
        return
    cache_path = os.environ.get("RAKATHON_RECIPE_CACHE_FILE", "").strip()
    if not cache_path:
        return
    if os.environ.get("RAKATHON_RECIPE_CACHE_READ_ONLY", "").strip() == "1":
        return
    try:
        clean = parse_recipe_strict(json.dumps(pending))
    except (OSError, ValueError, TypeError):
        return
    target = Path(cache_path)
    probe = target if target.exists() else target.parent
    if probe.exists() and not os.access(str(probe), os.W_OK):
        return
    try:
        cache = RecipeCache(target)
        cache.put(fingerprint, clean)
    except (OSError, ValueError, TypeError):
        return


def _main(argv: Sequence[str] | None) -> int:
    args = build_parser().parse_args(argv)
    started = time.monotonic()
    if args.check:
        try:
            extract_file(str(args.input))
        except (ConverterError, ManualReviewNeeded) as exc:
            sys.stderr.write(json.dumps({"error": exc.code}) + "\n")
            return EXIT_REJECTED
        _summary("check-ok", {}, False, time.monotonic() - started)
        return EXIT_OK
    if args.extract:
        return _extract_only(args, started)
    if needs_file_lane(str(args.input)):
        return run_file_flow(args, started)
    adaptive_info: dict[str, Any] = {
        "newFormat": False,
        "recipeReuse": False,
        "plannerMode": "none",
        "attempts": ["known_bypass:ok"],
        "fingerprint": "",
    }
    try:
        pre = _read_raw_for_unknown(str(args.input))
        if pre is not None:
            raw_pre, suffix_pre, name_pre = pre
            _write_progress(args, "planner_start", {"newFormat": True, "attempts": []})
            extracted, adaptive_info = _unknown_flow(args, raw_pre, suffix_pre, name_pre)
            _write_progress(args, "decode_done", adaptive_info)
        else:
            _clear_last()
            _write_progress(args, "known_start", adaptive_info)
            extracted = extract_file(str(args.input))
    except ManualReviewNeeded as exc:
        if exc.code == "scan_no_ocr" and args.allow_azure and args.secret_file:
            return run_file_flow(args, started)
        return _manual_exit(args, exc.code, exc.message, None, started, EXIT_OK)
    except ConverterError as exc:
        return _manual_exit(args, exc.code, exc.message, None, started, EXIT_REJECTED)
    conflict, _ = detect_identity_conflict(extracted.text)
    if conflict:
        return _manual_exit(
            args,
            "conflicting_identity",
            "pages carry conflicting ids",
            extracted,
            started,
            EXIT_OK,
        )
    if not args.allow_azure:
        return _manual_exit(
            args,
            "azure_not_opted_in",
            "azure inference needs --allow-azure plus a secret",
            extracted,
            started,
            EXIT_OK,
        )
    if not args.secret_file:
        return _manual_exit(
            args,
            "secret_missing",
            "azure inference needs --secret-file",
            extracted,
            started,
            EXIT_OK,
        )
    try:
        api_key = read_secret_file(str(args.secret_file))
    except AgentError as exc:
        return _manual_exit(args, exc.code, exc.message, extracted, started, EXIT_OK)
    try:
        prompt = build_prompt(extracted)
    except (OSError, ValueError) as exc:
        return _manual_exit(args, "prompt_failed", str(exc), extracted, started, EXIT_OK)
    _write_progress(args, "fhir_start", adaptive_info)
    try:
        raw = run_model_once(
            prompt,
            provider_id=str(args.provider_id),
            model=str(args.model),
            base_url=str(args.base_url),
            api_key=api_key,
            startup_timeout=float(args.startup_timeout),
            inference_timeout=float(args.inference_timeout),
            total_timeout=float(args.total_timeout),
        )
    except AgentError as exc:
        return _manual_exit(args, exc.code, exc.message, extracted, started, EXIT_OK)
    runtime_s = time.monotonic() - started
    draft: dict[str, Any] | None = None
    if raw.strip():
        draft = build_model_draft(
            raw, extracted.source_sha256, str(args.provider_id), str(args.model)
        )
    try:
        parsed = parse_model_output_strict(raw)
        checked = check_evidence(parsed, extracted, conflict=False)
    except OutputError as exc:
        return _manual_exit(
            args, exc.code, exc.message, extracted, started, EXIT_MODEL_FAILED, draft
        )
    result, bundle, provenance = assemble_result(
        checked,
        extracted,
        model_present=True,
        provider_id=str(args.provider_id),
        model=str(args.model),
        runtime_s=runtime_s,
    )
    _attach_adaptive(result, provenance, adaptive_info)
    try:
        write_outputs(Path(str(args.output)), result, bundle, provenance)
    except OutputError as exc:
        sys.stderr.write(json.dumps({"error": exc.code}) + "\n")
        return EXIT_MODEL_FAILED
    _retain_draft(Path(str(args.output)), draft)
    _commit_recipe_if_validated(adaptive_info, str(result.get("status", "")))
    _report_stored(result, runtime_s)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
