from __future__ import annotations

import json
from threading import Event
from typing import Any

from rakathon_backend.common.errors import ContractError
from rakathon_backend.converter.model_draft import is_valid_draft
from rakathon_backend.uploads.review_helpers import REVIEW_APPROVED_BLOB, REVIEW_STATE_BLOB
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.uploads.transcription_artifact import parse_transcription_bytes
from rakathon_backend.web.context_budget import ByteBudget, context_too_large
from rakathon_backend.web.contracts import WebError


def _blob(store: UploadStore, job_id: str, name: str, budget: ByteBudget) -> bytes | None:
    budget.check()
    raw = store.read_result_blob(job_id, name, max_bytes=budget.remaining)
    budget.consume(len(raw) if raw is not None else 0)
    return raw


def _json_blob(store: UploadStore, job_id: str, name: str, budget: ByteBudget) -> Any:
    raw = _blob(store, job_id, name, budget)
    return json.loads(raw) if raw is not None else None


def _check_patient(value: Any, case_id: str) -> None:
    if isinstance(value, dict):
        if value.get("resourceType") == "Patient" and value.get("id") != case_id:
            raise WebError(503, "unavailable", "Upload patient association mismatch")
        ref = value.get("reference")
        if isinstance(ref, str) and "Patient/" in ref and ref != f"Patient/{case_id}":
            raise WebError(503, "unavailable", "Upload patient association mismatch")
        for child in value.values():
            _check_patient(child, case_id)
    elif isinstance(value, list):
        for child in value:
            _check_patient(child, case_id)


def _check_text(text: str, case_id: str) -> None:
    try:
        value = json.loads(text)
    except ValueError:
        return
    _check_patient(value, case_id)


def collect_uploads(
    store: UploadStore | None,
    case_id: str,
    max_bytes: int = 900_000,
    cancelled: Event | None = None,
) -> list[dict[str, Any]]:
    try:
        return _collect_uploads(store, case_id, max_bytes, cancelled)
    except ContractError as exc:
        if exc.code == "resource_limit":
            raise context_too_large() from exc
        raise


def _collect_uploads(
    store: UploadStore | None, case_id: str, max_bytes: int, cancelled: Event | None
) -> list[dict[str, Any]]:
    if store is None:
        return []
    result: list[dict[str, Any]] = []
    reads, output = ByteBudget(max_bytes, cancelled), ByteBudget(max_bytes, cancelled)
    reads.check()
    for job in store.list_case(case_id, max_bytes=max_bytes):
        reads.charge(job)
        job_id = str(job["id"])
        item: dict[str, Any] = {
            "id": job_id,
            "status": job["status"],
            "filename": job["filename"],
            "artifacts": [],
            "unavailable": [],
        }
        raw = _blob(store, job_id, "transcription", reads)
        if raw is not None:
            transcription = parse_transcription_bytes(raw, str(job.get("sha256", "")))
            if transcription is None:
                item["unavailable"].append("invalid transcription")
            else:
                item["artifacts"].append(
                    {"trust": "transcription (unverified)", "transcription": transcription}
                )
        approved = _json_blob(store, job_id, REVIEW_APPROVED_BLOB, reads)
        if approved is not None:
            _check_patient(approved, case_id)
            item["artifacts"].append({"trust": "approved", "bundle": approved})
        state = _json_blob(store, job_id, REVIEW_STATE_BLOB, reads)
        if state is not None:
            if state.get("caseId") != case_id:
                raise WebError(503, "unavailable", "Upload patient association mismatch")
            item["reviewStatus"] = state.get("state")
            candidate = state.get("candidateText")
            if isinstance(candidate, str) and candidate and approved is None:
                _check_text(candidate, case_id)
                item["artifacts"].append({"trust": "pending draft", "text": candidate})
        draft = _json_blob(store, job_id, "model-draft", reads)
        if draft is not None:
            if is_valid_draft(draft, str(job.get("sha256", ""))):
                candidate = draft.get("candidateText")
                if isinstance(candidate, str) and candidate:
                    _check_text(candidate, case_id)
                _check_text(draft["modelOutputText"], case_id)
                item["artifacts"].append({"trust": "pending draft", "modelDraft": draft})
            else:
                item["unavailable"].append("invalid model draft")
        if state is None and draft is None and approved is None:
            legacy = _json_blob(store, job_id, "bundle", reads)
            if legacy is not None:
                _check_patient(legacy, case_id)
                item["artifacts"].append({"trust": "pending draft", "bundle": legacy})
        if not item["artifacts"]:
            item["unavailable"].append("no readable artifacts")
        output.charge(item)
        output.consume(1)
        result.append(item)
    return result
