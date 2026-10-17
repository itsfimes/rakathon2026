from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from rakathon_backend.common.errors import ContractError
from rakathon_backend.uploads.review_validation import validate_candidate_text

REVIEW_STATE_BLOB = "review-state"
REVIEW_APPROVED_BLOB = "review-approved"
TRANSCRIPTION_METHOD = "opencode-native-files"
NOT_INVOKED_CODES = frozenset(
    {
        "image_no_ocr",
        "scan_no_ocr",
        "azure_not_opted_in",
        "secret_missing",
        "secret_empty",
        "secret_unreadable",
        "secret_not_file",
        "secret_permissions",
        "secret_symlink",
        "tiff_unsupported",
        "not_file_lane",
        "file_page_limit",
        "unsupported_file",
        "image_unreadable",
    }
)
FAILED_CODES = frozenset(
    {
        "session_failed",
        "inference_failed",
        "process_failed",
        "agent_timeout",
        "agent_failed",
        "untrusted_endpoint",
        "bad_timeout",
        "transcript_failed",
        "transcript_bad_json",
        "transcript_too_large",
        "transcript_page_mismatch",
        "transcript_bad_shape",
        "transcript_no_text",
        "fhir_failed",
        "fhir_too_large",
        "conflicting_identity",
        "exit_mismatch",
        "converter_failed",
        "missing_artifact",
        "malformed_json",
        "bad_envelope",
        "sha_mismatch",
        "invalid_fhir",
        "missing_bundle",
        "no_docker",
        "convert_error",
        "original_unavailable",
        "store_unavailable",
    }
)
MAX_HISTORY = 64
MAX_STATE_BYTES = 524288
STATES = frozenset(
    {"pending", "draft", "importing", "imported", "import-failed", "import-uncertain"}
)
BLOCK_EDIT = frozenset({"importing", "imported", "import-uncertain"})
BLOCK_CLAIM = frozenset({"importing", "imported", "import-uncertain"})


def rev_blob(revision: int) -> str:
    return f"review-rev-{revision:06d}"


def approval_id(job_id: str, revision: int, candidate_hash: str) -> str:
    return f"rev-{job_id[:12]}-r{revision}-{candidate_hash[:16]}"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def empty_assessment(patient_id: str, code: str) -> dict[str, Any]:
    message = "no model draft retained" if code == "empty_draft" else "no candidate text"
    return {
        "valid": False,
        "issues": [{"code": code, "path": "", "message": message}],
        "counts": {},
        "patientRef": "Patient/" + patient_id,
        "candidateHash": None,
    }


def assess(text: str, patient_id: str) -> dict[str, Any]:
    try:
        seen: dict[str, Any] = validate_candidate_text(text, patient_id)
    except ContractError as exc:
        return {
            "valid": False,
            "issues": [{"code": exc.code, "path": "", "message": exc.message}],
            "counts": {},
            "patientRef": "Patient/" + patient_id,
            "candidateHash": None,
        }
    return {
        "valid": True,
        "issues": [],
        "counts": dict(seen.get("counts", {})),
        "patientRef": str(seen.get("patientRef", "Patient/" + patient_id)),
        "candidateHash": str(seen.get("candidateHash", "")),
    }


def sanitize_receipt(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise ContractError(code="bad_receipt", message="import receipt invalid")
    if receipt.get("resourceType") != "Bundle":
        raise ContractError(code="bad_receipt", message="import receipt invalid")
    if receipt.get("type") != "transaction-response":
        raise ContractError(code="bad_receipt", message="import receipt invalid")
    entries = receipt.get("entry")
    if not isinstance(entries, list) or not entries:
        raise ContractError(code="bad_receipt", message="import receipt invalid")
    clean: dict[str, Any] = copy.deepcopy(receipt)
    raw = json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > 65536:
        raise ContractError(code="bad_receipt", message="import receipt too large")
    out: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "transaction-response",
        "entry": clean["entry"],
    }
    if isinstance(clean.get("alreadyApplied"), bool):
        out["alreadyApplied"] = clean["alreadyApplied"]
    return out


def _job_codes(job: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    reason = job.get("reason")
    if isinstance(reason, str) and reason:
        codes.append(reason[:64])
    issues = job.get("issues")
    if isinstance(issues, list):
        for item in issues[:8]:
            if isinstance(item, dict):
                code = item.get("code")
                if isinstance(code, str) and code:
                    codes.append(code[:64])
            elif isinstance(item, str) and item:
                codes.append(item[:64])
    return codes


def derive_draft_reason(job: dict[str, Any]) -> str:
    for code in _job_codes(job):
        if code in NOT_INVOKED_CODES:
            return "model-not-invoked:" + code
    for code in _job_codes(job):
        if code in FAILED_CODES:
            return "model-failed:" + code
    if _job_codes(job):
        return "model-failed:unknown"
    if job.get("fhirStatus") is not None or job.get("modelMode") is not None:
        return "model-failed:unknown"
    return "legacy-draft-missing"


def provenance_has_transcription(prov_raw: bytes | None, expected_sha: str) -> bool:
    if prov_raw is None or not expected_sha:
        return False
    try:
        doc: Any = json.loads(prov_raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False
    if not isinstance(doc, dict):
        return False
    marker = doc.get("transcription")
    if not isinstance(marker, dict):
        return False
    if marker.get("method") != TRANSCRIPTION_METHOD:
        return False
    if marker.get("untrusted") is not True:
        return False
    direct = marker.get("source_sha256")
    compat = marker.get("sourceSha256")
    return not (direct != expected_sha and compat != expected_sha)
