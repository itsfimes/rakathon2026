from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from rakathon_backend.common.errors import ContractError
from rakathon_backend.uploads.review_validation import validate_candidate_text

REVIEW_STATE_BLOB = "review-state"
REVIEW_APPROVED_BLOB = "review-approved"
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
