from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.fhir import resource_counts, validate_bundle
from rakathon_backend.converter.model_draft import is_valid_draft, read_draft_bytes
from rakathon_backend.converter.planner import parse_recipe_strict
from rakathon_backend.uploads.transcription_artifact import load_valid_transcription

if TYPE_CHECKING:
    from pathlib import Path

    from rakathon_backend.converter.planner import RecipeCache
    from rakathon_backend.uploads.store import UploadStore


def recipe_from_provenance(prov: dict[str, Any]) -> list[dict[str, Any]] | None:
    adaptive: Any = prov.get("adaptive", {})
    if not isinstance(adaptive, dict):
        return None
    if adaptive.get("plannerMode") != "planner":
        return None
    pending: Any = prov.get("pendingRecipe")
    if not isinstance(pending, dict):
        return None
    try:
        clean = parse_recipe_strict(json.dumps(pending))
    except (ValueError, TypeError):
        return None
    steps = clean.get("steps")
    if isinstance(steps, list) and steps:
        out: list[dict[str, Any]] = []
        for entry in steps:
            if isinstance(entry, dict):
                out.append(dict(entry))
        return out or None
    return None


def _persist_model_draft(store: Any, job_id: str, expected_sha: str, out_dir: Path) -> None:
    raw = read_draft_bytes(out_dir)
    if raw is None:
        return
    try:
        doc: Any = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return
    if not is_valid_draft(doc, expected_sha):
        return
    try:
        store.write_result_blob(job_id, "model-draft", raw)
    except (OSError, ContractError, ValueError, RuntimeError):
        return


def _persist_transcription(store: Any, job_id: str, expected_sha: str, out_dir: Path) -> None:
    raw = load_valid_transcription(out_dir, expected_sha)
    if raw is None:
        return
    try:
        store.write_result_blob(job_id, "transcription", raw)
    except (OSError, ContractError, ValueError, RuntimeError):
        return


def collect_result(
    store: UploadStore,
    cache: RecipeCache,
    allow_azure: bool,
    job_id: str,
    out_dir: Path,
    code: int,
) -> None:
    job = store.get(job_id)
    if job is None:
        return
    expected_sha = str(job.get("sha256", ""))
    _persist_model_draft(store, job_id, expected_sha, out_dir)
    _persist_transcription(store, job_id, expected_sha, out_dir)
    try:
        result_raw = (out_dir / "result.json").read_bytes()
        prov_raw = (out_dir / "provenance.json").read_bytes()
    except OSError:
        store.finish(job_id, "failed", {"reason": "missing_artifact"})
        return
    try:
        result: Any = json.loads(result_raw.decode("utf-8"))
        prov: Any = json.loads(prov_raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        store.finish(job_id, "failed", {"reason": "malformed_json"})
        return
    if not isinstance(result, dict) or not isinstance(prov, dict):
        store.finish(job_id, "failed", {"reason": "bad_envelope"})
        return
    for key in ("status", "needsReview", "writeEligible", "persistence", "model", "source"):
        if key not in result:
            store.finish(job_id, "failed", {"reason": "bad_envelope"})
            return
    if result.get("needsReview") is not True or result.get("writeEligible") is not False:
        store.finish(job_id, "failed", {"reason": "bad_envelope"})
        return
    if result.get("persistence") != "not-written":
        store.finish(job_id, "failed", {"reason": "bad_envelope"})
        return
    model = result.get("model")
    if not isinstance(model, dict) or not isinstance(model.get("present"), bool):
        store.finish(job_id, "failed", {"reason": "bad_envelope"})
        return
    status = str(result.get("status", "manual-review"))
    source = result.get("source")
    if status == "complete":
        if not isinstance(source, dict) or source.get("sha256") != expected_sha:
            store.finish(job_id, "failed", {"reason": "sha_mismatch"})
            return
        if prov.get("sourceSha256") != expected_sha:
            store.finish(job_id, "failed", {"reason": "sha_mismatch"})
            return
        if model.get("present") is not True:
            store.finish(job_id, "failed", {"reason": "bad_envelope"})
            return
    else:
        if (
            isinstance(source, dict)
            and source.get("sha256") is not None
            and source.get("sha256") != expected_sha
        ):
            store.finish(job_id, "failed", {"reason": "sha_mismatch"})
            return
        if (
            str(prov.get("sourceSha256", "")) not in ("", expected_sha)
            and prov.get("sourceSha256") != expected_sha
        ):
            store.finish(job_id, "failed", {"reason": "sha_mismatch"})
            return
    if code != 0 and status == "complete":
        store.finish(job_id, "failed", {"reason": "exit_mismatch"})
        return
    bundle: Any = result.get("bundle")
    validated: dict[str, Any] | None = None
    if bundle is not None:
        if not isinstance(bundle, dict):
            store.finish(job_id, "failed", {"reason": "invalid_fhir"})
            return
        if bundle.get("resourceType") == "OperationOutcome":
            store.finish(job_id, "failed", {"reason": "invalid_fhir"})
            return
        try:
            if not validate_bundle(bundle):
                raise ContractError(code="bad_payload", message="invalid bundle")
            if str(bundle.get("meta", {}).get("source", "")) not in (
                "",
                f"urn:sha256:{expected_sha}",
            ):
                meta_src = str(bundle.get("meta", {}).get("source", ""))
                if meta_src and meta_src != f"urn:sha256:{expected_sha}":
                    raise ContractError(code="bad_payload", message="source mismatch")
        except ContractError:
            store.finish(job_id, "failed", {"reason": "invalid_fhir"})
            return
        validated = bundle
    if status == "complete" and validated is None:
        store.finish(job_id, "failed", {"reason": "missing_bundle"})
        return
    bundle_raw: bytes = b""
    try:
        bundle_raw = (out_dir / "bundle.json").read_bytes()
    except OSError:
        bundle_raw = b""
    if validated is not None and bundle_raw:
        try:
            secondary: Any = json.loads(bundle_raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            store.finish(job_id, "failed", {"reason": "invalid_fhir"})
            return
        if not isinstance(secondary, dict) or secondary != validated:
            store.finish(job_id, "failed", {"reason": "invalid_fhir"})
            return
    try:
        store.write_result_blob(job_id, "result", result_raw)
        store.write_result_blob(job_id, "provenance", prov_raw)
    except (OSError, ContractError, ValueError, RuntimeError):
        store.finish(job_id, "failed", {"reason": "store_unavailable"})
        return
    if validated is not None:
        canonical = json.dumps(validated, sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            store.write_result_blob(job_id, "bundle", canonical)
        except (OSError, ContractError, ValueError, RuntimeError):
            pass
    counts = resource_counts(validated) if validated is not None else {}
    final = (
        "complete"
        if status == "complete"
        else ("manual-review" if status in ("manual-review", "incomplete") else "failed")
    )
    if final == "failed":
        store.finish(job_id, "failed", {"reason": "converter_failed"})
        return
    adaptive: Any = result.get("adaptive", {})
    if not isinstance(adaptive, dict):
        adaptive = {}
    patch: dict[str, Any] = {
        "counts": counts,
        "recipeReuse": bool(adaptive.get("recipeReuse", False)),
        "newFormat": bool(adaptive.get("newFormat", False)),
        "plannerMode": str(adaptive.get("plannerMode", "fallback")),
        "fhirStatus": status,
        "modelMode": "azure" if allow_azure else "offline",
    }
    issues = result.get("issues")
    if isinstance(issues, list):
        patch["issues"] = issues[:8]
    store.finish(job_id, final, patch)
    fingerprint = str(adaptive.get("fingerprint", ""))
    if final == "complete" and fingerprint and validated is not None:
        steps = recipe_from_provenance(prov)
        if steps is not None:
            cache.put(fingerprint, {"version": 1, "steps": steps})
