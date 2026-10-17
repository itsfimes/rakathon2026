from __future__ import annotations

import json
from typing import Any

from rakathon_backend.converter.model_draft import is_valid_draft
from rakathon_backend.uploads.review_helpers import REVIEW_APPROVED_BLOB
from rakathon_backend.uploads.review_state import read_state
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.uploads.transcription_artifact import parse_transcription_bytes
from rakathon_backend.web.contracts import WebError


def _json_blob(store: UploadStore, job_id: str, name: str) -> Any:
    raw = store.read_result_blob(job_id, name)
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


def collect_uploads(store: UploadStore | None, case_id: str) -> list[dict[str, Any]]:
    if store is None:
        return []
    result: list[dict[str, Any]] = []
    for job in store.list_case(case_id):
        job_id = str(job["id"])
        item: dict[str, Any] = {
            "id": job_id,
            "status": job["status"],
            "filename": job["filename"],
            "artifacts": [],
            "unavailable": [],
        }
        raw = store.read_result_blob(job_id, "transcription")
        if raw is not None:
            transcription = parse_transcription_bytes(raw, str(job.get("sha256", "")))
            if transcription is None:
                item["unavailable"].append("invalid transcription")
            else:
                item["artifacts"].append(
                    {"trust": "transcription (unverified)", "transcription": transcription}
                )
        approved = _json_blob(store, job_id, REVIEW_APPROVED_BLOB)
        if approved is not None:
            _check_patient(approved, case_id)
            item["artifacts"].append({"trust": "approved", "bundle": approved})
        state = read_state(store, job_id)
        if state is not None:
            if state.get("caseId") != case_id:
                raise WebError(503, "unavailable", "Upload patient association mismatch")
            item["reviewStatus"] = state.get("state")
            candidate = state.get("candidateText")
            if isinstance(candidate, str) and candidate and approved is None:
                _check_text(candidate, case_id)
                item["artifacts"].append({"trust": "pending draft", "text": candidate})
        draft = _json_blob(store, job_id, "model-draft")
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
            legacy = _json_blob(store, job_id, "bundle")
            if legacy is not None:
                _check_patient(legacy, case_id)
                item["artifacts"].append({"trust": "pending draft", "bundle": legacy})
        result.append(item)
    return result
