from __future__ import annotations

import copy
import json
from typing import Any

from rakathon_backend.common.errors import ContractError
from rakathon_backend.converter.model_draft import is_valid_draft
from rakathon_backend.uploads.review_helpers import (
    MAX_HISTORY,
    MAX_STATE_BYTES,
    REVIEW_STATE_BLOB,
    assess,
    empty_assessment,
    rev_blob,
    text_hash,
)
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.uploads.store_io import now_iso


def read_state(uploads: UploadStore, job_id: str) -> dict[str, Any] | None:
    raw = uploads.read_result_blob(job_id, REVIEW_STATE_BLOB)
    if raw is None:
        return None
    try:
        doc: Any = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ContractError(code="store_unavailable", message="review store unavailable") from exc
    if not isinstance(doc, dict):
        raise ContractError(code="store_unavailable", message="review store unavailable")
    return doc


def persist_state(uploads: UploadStore, job_id: str, state: dict[str, Any]) -> None:
    hist = state.get("history")
    if not isinstance(hist, list) or len(hist) > MAX_HISTORY:
        raise ContractError(code="too_large", message="review audit too large")
    raw = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_STATE_BYTES:
        raise ContractError(code="too_large", message="review state too large")
    uploads.write_result_blob(job_id, REVIEW_STATE_BLOB, raw)


def persist_revision(
    uploads: UploadStore,
    job_id: str,
    revision: int,
    text: str,
    actor: str,
    at: str,
    source_urn: str,
) -> None:
    doc = {
        "revision": revision,
        "candidateText": text,
        "candidateHash": text_hash(text),
        "actor": actor,
        "at": at,
        "sourceUrn": source_urn,
    }
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_STATE_BYTES:
        raise ContractError(code="too_large", message="review revision too large")
    uploads.write_result_blob(job_id, rev_blob(revision), raw)


def seed_state(uploads: UploadStore, job: dict[str, Any]) -> dict[str, Any]:
    job_id = str(job["id"])
    sha = str(job.get("sha256", ""))
    case_id = str(job.get("caseId", ""))
    urn = str(job.get("sourceUrn", f"urn:sha256:{sha}"))
    candidate = ""
    available = False
    reason: str | None = "legacy-draft-missing"
    draft_raw = uploads.read_result_blob(job_id, "model-draft")
    if draft_raw is not None:
        try:
            doc: Any = json.loads(draft_raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            doc = None
        if is_valid_draft(doc, sha) and isinstance(doc, dict):
            cand = doc.get("candidateText")
            if isinstance(cand, str) and cand:
                candidate = cand
                available = True
                reason = None
    if not candidate:
        bundle_raw = uploads.read_result_blob(job_id, "bundle")
        if bundle_raw is not None:
            try:
                bundle: Any = json.loads(bundle_raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                bundle = None
            if isinstance(bundle, dict) and bundle.get("resourceType") == "Bundle":
                candidate = json.dumps(bundle, indent=2)
                available = False
                reason = "legacy-bundle-fallback"
    assessed = assess(candidate, case_id) if candidate else empty_assessment(case_id, "empty_draft")
    at = now_iso()
    state: dict[str, Any] = {
        "revision": 0,
        "state": "pending",
        "candidateText": candidate,
        "candidateHash": assessed["candidateHash"],
        "sourceUrn": urn,
        "sourceSha256": sha,
        "caseId": case_id,
        "modelDraftAvailable": available,
        "modelDraftReason": reason,
        "updatedAt": at,
        "reviewedBy": None,
        "approvalId": None,
        "approvalHash": None,
        "approvalAt": None,
        "importReceipt": None,
        "history": [{"rev": 0, "action": "seed", "actor": "system", "at": at, "hash": None}],
    }
    persist_revision(uploads, job_id, 0, candidate, "system", at, urn)
    persist_state(uploads, job_id, state)
    return state


def public_view(state: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    case_id = str(state.get("caseId", job.get("caseId", "")))
    text = str(state.get("candidateText", ""))
    assessed = assess(text, case_id) if text else empty_assessment(case_id, "empty_draft")
    validation: dict[str, Any] = {
        "valid": bool(assessed["valid"]),
        "issues": list(assessed["issues"]),
        "counts": dict(assessed["counts"]),
        "patientRef": str(assessed["patientRef"]),
        "sourceUrn": str(state.get("sourceUrn", job.get("sourceUrn", ""))),
        "sourceSha256": str(state.get("sourceSha256", job.get("sha256", ""))),
        "modelDraftAvailable": bool(state.get("modelDraftAvailable", False)),
        "updatedAt": str(state.get("updatedAt", "")),
        "reviewedBy": state.get("reviewedBy"),
        "importReceipt": copy.deepcopy(state.get("importReceipt")),
    }
    return {
        "jobId": str(job["id"]),
        "revision": int(state.get("revision", 0)),
        "state": str(state.get("state", "pending")),
        "candidateText": text,
        "validation": validation,
        "counts": dict(assessed["counts"]),
        "patientRef": str(assessed["patientRef"]),
        "sourceUrn": str(state.get("sourceUrn", job.get("sourceUrn", ""))),
        "sourceSha256": str(state.get("sourceSha256", job.get("sha256", ""))),
        "caseId": case_id,
        "modelDraftAvailable": bool(state.get("modelDraftAvailable", False)),
        "modelDraftReason": state.get("modelDraftReason"),
        "updatedAt": str(state.get("updatedAt", "")),
        "reviewedBy": state.get("reviewedBy"),
        "importReceipt": copy.deepcopy(state.get("importReceipt")),
        "approvalId": state.get("approvalId"),
    }
