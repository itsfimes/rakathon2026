from __future__ import annotations

import copy
import json
import threading
from typing import Any

from rakathon_backend.common.errors import ContractError
from rakathon_backend.converter.model_draft import is_valid_draft
from rakathon_backend.uploads.review_helpers import (
    BLOCK_CLAIM,
    BLOCK_EDIT,
    REVIEW_APPROVED_BLOB,
    approval_id,
    assess,
    empty_assessment,
    sanitize_receipt,
    text_hash,
)
from rakathon_backend.uploads.review_state import (
    persist_revision,
    persist_state,
    public_view,
    read_state,
    seed_state,
)
from rakathon_backend.uploads.review_validation import (
    MAX_CANDIDATE_BYTES,
    prepare_review_import,
    validate_candidate_text,
)
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.uploads.store_io import now_iso


class ReviewStore:
    def __init__(self, uploads: UploadStore) -> None:
        self._uploads = uploads
        self._lock = threading.RLock()
        self._fresh: set[str] = set()

    def _require_job(self, job_id: str, user_id: str) -> dict[str, Any]:
        job = self._uploads.get(job_id.lower() if isinstance(job_id, str) else "")
        if job is None:
            raise ContractError(code="not_found", message="review not found")
        if job.get("owner") != user_id:
            raise ContractError(code="forbidden", message="review forbidden")
        if job.get("status") in ("queued", "running"):
            raise ContractError(code="review_unavailable", message="review not ready")
        return job

    def _require_system_job(self, job_id: str) -> dict[str, Any]:
        job = self._uploads.get(job_id.lower() if isinstance(job_id, str) else "")
        if job is None:
            raise ContractError(code="not_found", message="review not found")
        return job

    def _load(self, job: dict[str, Any]) -> dict[str, Any]:
        job_id = str(job["id"])
        state = read_state(self._uploads, job_id)
        if state is None:
            return seed_state(self._uploads, job)
        if state.get("state") == "importing" and job_id not in self._fresh:
            at = now_iso()
            hist = state.get("history")
            if isinstance(hist, list):
                hist.append(
                    {
                        "rev": int(state.get("revision", 0)),
                        "action": "restart-marked-uncertain",
                        "actor": "system",
                        "at": at,
                        "hash": None,
                    }
                )
            state["state"] = "import-uncertain"
            state["updatedAt"] = at
            persist_state(self._uploads, job_id, state)
        return state

    def get(self, job_id: str, user_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._require_job(job_id, user_id)
            return public_view(self._load(job), job)

    def summary(self, job_id: str, user_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._require_job(job_id, user_id)
            public = public_view(self._load(job), job)
            validation = public["validation"]
            return {
                "jobId": str(job["id"]),
                "revision": int(public["revision"]),
                "state": str(public["state"]),
                "updatedAt": str(public["updatedAt"]),
                "sourceUrn": str(public["sourceUrn"]),
                "caseId": str(public["caseId"]),
                "valid": bool(validation["valid"]),
                "modelDraftAvailable": bool(public["modelDraftAvailable"]),
                "reviewedBy": public["reviewedBy"],
            }

    def save(
        self, job_id: str, user_id: str, expected_revision: int, candidate_text: str
    ) -> dict[str, Any]:
        with self._lock:
            if not isinstance(candidate_text, str):
                raise ContractError(code="bad_payload", message="candidate text invalid")
            if len(candidate_text.encode("utf-8")) > MAX_CANDIDATE_BYTES:
                raise ContractError(code="oversize", message="candidate text too large")
            job = self._require_job(job_id, user_id)
            state = self._load(job)
            if str(state.get("state")) in BLOCK_EDIT:
                raise ContractError(code="conflict", message="review locked for import")
            if int(state.get("revision", 0)) != int(expected_revision):
                raise ContractError(code="conflict", message="stale review revision")
            case_id = str(state.get("caseId", job.get("caseId", "")))
            assessed = (
                assess(candidate_text, case_id)
                if candidate_text
                else empty_assessment(case_id, "empty_draft")
            )
            new_rev = int(state.get("revision", 0)) + 1
            at = now_iso()
            state["revision"] = new_rev
            state["state"] = "draft"
            state["candidateText"] = candidate_text
            state["candidateHash"] = assessed["candidateHash"]
            state["updatedAt"] = at
            state["reviewedBy"] = user_id
            state["approvalId"] = None
            state["approvalHash"] = None
            state["approvalAt"] = None
            hist = state.get("history")
            if isinstance(hist, list):
                hist.append(
                    {
                        "rev": new_rev,
                        "action": "save",
                        "actor": user_id,
                        "at": at,
                        "hash": text_hash(candidate_text),
                    }
                )
            urn = str(state.get("sourceUrn", job.get("sourceUrn", "")))
            persist_revision(self._uploads, job_id, new_rev, candidate_text, user_id, at, urn)
            persist_state(self._uploads, job_id, state)
            return public_view(state, job)

    def claim_import(
        self, job_id: str, user_id: str, expected_revision: int, patient_confirmed: bool
    ) -> dict[str, Any]:
        with self._lock:
            job = self._require_job(job_id, user_id)
            state = self._load(job)
            current = str(state.get("state"))
            if current == "imported":
                if int(state.get("revision", 0)) != int(expected_revision):
                    raise ContractError(code="conflict", message="stale review revision")
                return {
                    "approvalId": state.get("approvalId"),
                    "revision": int(state.get("revision", 0)),
                    "state": "imported",
                    "alreadyImported": True,
                    "receipt": copy.deepcopy(state.get("importReceipt")),
                }
            if current in BLOCK_CLAIM:
                raise ContractError(code="conflict", message="import already claimed")
            if int(state.get("revision", 0)) != int(expected_revision):
                raise ContractError(code="conflict", message="stale review revision")
            if patient_confirmed is not True:
                raise ContractError(
                    code="confirmation_required", message="explicit confirmation required"
                )
            text = str(state.get("candidateText", ""))
            case_id = str(state.get("caseId", job.get("caseId", "")))
            urn = str(state.get("sourceUrn", job.get("sourceUrn", "")))
            try:
                seen: dict[str, Any] = validate_candidate_text(text, case_id)
            except ContractError as exc:
                raise ContractError(code="invalid_candidate", message=str(exc.message)) from exc
            chash = str(seen.get("candidateHash", ""))
            approval = approval_id(str(job["id"]), int(state.get("revision", 0)), chash)
            try:
                prepared: dict[str, Any] = prepare_review_import(
                    text,
                    patient_id=case_id,
                    source_urn=urn,
                    approval_id=approval,
                    patient_confirmed=True,
                )
            except ContractError as exc:
                raise ContractError(code="invalid_candidate", message=str(exc.message)) from exc
            at = now_iso()
            state["state"] = "importing"
            state["approvalId"] = approval
            state["approvalHash"] = chash
            state["approvalAt"] = at
            state["updatedAt"] = at
            state["reviewedBy"] = user_id
            hist = state.get("history")
            if isinstance(hist, list):
                hist.append(
                    {
                        "rev": int(state.get("revision", 0)),
                        "action": "claim-import",
                        "actor": user_id,
                        "at": at,
                        "hash": chash,
                    }
                )
            persist_state(self._uploads, job_id, state)
            self._fresh.add(str(job["id"]))
            return {
                "approvalId": approval,
                "revision": int(state.get("revision", 0)),
                "state": "importing",
                "prepared": prepared,
                "candidateHash": chash,
            }

    def record_import(
        self, job_id: str, approval_id: str, receipt: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            job = self._require_system_job(job_id)
            state = self._load(job)
            current = str(state.get("state"))
            if current == "imported":
                if state.get("approvalId") == approval_id:
                    return public_view(state, job)
                raise ContractError(code="approval_mismatch", message="approval mismatch")
            if current not in ("importing", "import-uncertain"):
                raise ContractError(code="approval_mismatch", message="no active approval")
            if state.get("approvalId") != approval_id:
                raise ContractError(code="approval_mismatch", message="approval mismatch")
            clean = sanitize_receipt(receipt)
            text = str(state.get("candidateText", ""))
            case_id = str(state.get("caseId", job.get("caseId", "")))
            urn = str(state.get("sourceUrn", job.get("sourceUrn", "")))
            prepared = prepare_review_import(
                text,
                patient_id=case_id,
                source_urn=urn,
                approval_id=str(approval_id),
                patient_confirmed=True,
            )
            bundle_raw = json.dumps(
                prepared["bundle"], sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            self._uploads.write_result_blob(job_id, REVIEW_APPROVED_BLOB, bundle_raw)
            at = now_iso()
            state["state"] = "imported"
            state["importReceipt"] = clean
            state["updatedAt"] = at
            hist = state.get("history")
            if isinstance(hist, list):
                hist.append(
                    {
                        "rev": int(state.get("revision", 0)),
                        "action": "imported",
                        "actor": "system",
                        "at": at,
                        "hash": str(state.get("approvalHash")),
                    }
                )
            persist_state(self._uploads, job_id, state)
            self._fresh.discard(str(job["id"]))
            return public_view(state, job)

    def record_failure(
        self, job_id: str, approval_id: str, code: str, uncertain: bool = False
    ) -> dict[str, Any]:
        with self._lock:
            job = self._require_system_job(job_id)
            state = self._load(job)
            current = str(state.get("state"))
            if current not in ("importing", "import-uncertain", "import-failed"):
                raise ContractError(code="approval_mismatch", message="no active approval")
            if state.get("approvalId") != approval_id:
                raise ContractError(code="approval_mismatch", message="approval mismatch")
            if not isinstance(code, str) or not code or len(code) > 64:
                raise ContractError(code="bad_request", message="failure code invalid")
            at = now_iso()
            action = "import-uncertain" if bool(uncertain) else "import-failed"
            state["state"] = action
            state["updatedAt"] = at
            hist = state.get("history")
            if isinstance(hist, list):
                hist.append(
                    {
                        "rev": int(state.get("revision", 0)),
                        "action": action,
                        "actor": "system",
                        "at": at,
                        "hash": str(code[:64]),
                    }
                )
            persist_state(self._uploads, job_id, state)
            if not bool(uncertain):
                self._fresh.discard(str(job["id"]))
            return public_view(state, job)

    def export_artifacts(self, job_id: str, user_id: str) -> dict[str, bytes]:
        with self._lock:
            job = self._require_job(job_id, user_id)
            state = self._load(job)
            public = public_view(state, job)
            out: dict[str, bytes] = {}
            out["review-draft.txt"] = str(state.get("candidateText", "")).encode("utf-8")
            out["review.json"] = json.dumps(public, indent=2).encode("utf-8")
            audit = {
                "jobId": str(job["id"]),
                "revision": int(state.get("revision", 0)),
                "state": str(state.get("state", "")),
                "history": copy.deepcopy(state.get("history", [])),
                "updatedAt": str(state.get("updatedAt", "")),
                "reviewedBy": state.get("reviewedBy"),
            }
            out["review-audit.json"] = json.dumps(audit, indent=2).encode("utf-8")
            if str(state.get("state")) == "imported":
                approved = self._uploads.read_result_blob(job_id, REVIEW_APPROVED_BLOB)
                if approved is None:
                    raise ContractError(code="store_unavailable", message="approved missing")
                out["approved-bundle.json"] = approved
                receipt = state.get("importReceipt")
                if receipt is None:
                    raise ContractError(code="store_unavailable", message="receipt missing")
                out["import-receipt.json"] = json.dumps(receipt, indent=2).encode("utf-8")
            return out

    def get_model_text(self, job_id: str, user_id: str) -> str | None:
        with self._lock:
            job = self._require_job(job_id, user_id)
            sha = str(job.get("sha256", ""))
            raw = self._uploads.read_result_blob(str(job["id"]), "model-draft")
            if raw is None:
                return None
            try:
                doc: Any = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return None
            if not is_valid_draft(doc, sha) or not isinstance(doc, dict):
                return None
            out = doc.get("modelOutputText")
            return out if isinstance(out, str) else None
