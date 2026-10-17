from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.uploads.http import UploadRoutes
from rakathon_backend.uploads.review_hooks import (
    APPROVE_ROLES,
    REVIEW_PATH_RE,
    contract_response,
    enrich,
    err,
    is_int,
    json_only,
    strict_dict,
)
from rakathon_backend.uploads.review_store import ReviewStore


class ReviewUploadRoutes:
    def __init__(
        self,
        base: UploadRoutes,
        reviews: ReviewStore,
        *,
        authorize_approve: Callable[[str], bool] | None = None,
        import_ready: Callable[[], bool] | None = None,
        importer: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self._base = base
        self._reviews = reviews
        self._authorize_approve = authorize_approve
        self._import_ready = import_ready
        self._importer = importer
        self._gate = threading.Lock()

    def handle(
        self,
        user_id: str,
        role: str,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> tuple[int, dict[str, str], Any] | None:
        parsed = REVIEW_PATH_RE.match(path)
        if parsed is not None:
            job_id = parsed.group(1).lower()
            suffix = parsed.group(2)
            if method == "GET" and suffix == "":
                return self._get_review(user_id, job_id)
            if method == "GET" and suffix == "/model":
                return self._get_model(user_id, job_id)
            if method == "POST" and suffix == "/draft":
                return self._post_draft(user_id, role, job_id, headers, body)
            if method == "POST" and suffix == "/approve":
                return self._post_approve(user_id, role, job_id, headers, body)
            return err(405, "method_not_allowed", "method not allowed")
        out = self._base.handle(user_id, role, method, path, headers, body)
        if out is None:
            return None
        return enrich(self._reviews, user_id, method, path, out)

    def _guarded(self, user_id: str, job_id: str) -> tuple[int, dict[str, str], Any] | None:
        _job, failed = self._base._guarded(user_id, job_id)
        if failed is not None:
            return failed
        return None

    def _flag(self, user_id: str, public: dict[str, Any]) -> tuple[bool, str | None]:
        state = str(public.get("state", ""))
        valid = bool(public.get("validation", {}).get("valid", False))
        if state == "imported":
            return (False, "already_imported")
        if state in ("importing", "import-uncertain"):
            return (False, "import_locked")
        if not valid:
            return (False, "invalid_candidate")
        try:
            ready = bool(self._import_ready() if self._import_ready is not None else False)
        except (OSError, ValueError, RuntimeError):
            return (False, "unavailable")
        if not ready:
            return (False, "not_configured")
        if self._authorize_approve is not None:
            try:
                allowed = bool(self._authorize_approve(user_id))
            except (OSError, ValueError, RuntimeError):
                return (False, "unavailable")
            if not allowed:
                return (False, "forbidden")
        return (True, None)

    def _get_review(self, user_id: str, job_id: str) -> tuple[int, dict[str, str], Any]:
        gate = self._guarded(user_id, job_id)
        if gate is not None:
            return gate
        try:
            public = self._reviews.get(job_id, user_id)
        except ContractError as exc:
            return contract_response(exc)
        enabled, reason = self._flag(user_id, public)
        return (
            200,
            {},
            {"version": 1, "review": public, "approvalEnabled": enabled, "approvalReason": reason},
        )

    def _get_model(self, user_id: str, job_id: str) -> tuple[int, dict[str, str], Any]:
        gate = self._guarded(user_id, job_id)
        if gate is not None:
            return gate
        try:
            text = self._reviews.get_model_text(job_id, user_id)
        except ContractError as exc:
            return contract_response(exc)
        return (200, {}, {"version": 1, "modelOutputText": text})

    def _post_draft(
        self, user_id: str, role: str, job_id: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, dict[str, str], Any]:
        if role not in APPROVE_ROLES:
            return err(403, "forbidden", "forbidden")
        if not json_only(headers):
            return err(422, "invalid_schema", "json body required")
        try:
            payload = strict_dict(body)
        except ValueError:
            return err(422, "invalid_schema", "body is not strict json")
        if set(payload.keys()) != {"revision", "candidateText"}:
            return err(422, "invalid_schema", "draft fields invalid")
        if not is_int(payload.get("revision")) or not isinstance(payload.get("candidateText"), str):
            return err(422, "invalid_schema", "draft fields invalid")
        gate = self._guarded(user_id, job_id)
        if gate is not None:
            return gate
        try:
            public = self._reviews.save(
                job_id, user_id, int(payload["revision"]), str(payload["candidateText"])
            )
        except ContractError as exc:
            if str(getattr(exc, "code", "")) == "conflict":
                try:
                    current = self._reviews.get(job_id, user_id)
                except ContractError:
                    return contract_response(exc)
                shaped: Any = {
                    "version": 1,
                    "error": {"code": "conflict", "message": str(exc.message)},
                }
                shaped["error"]["currentRevision"] = int(current.get("revision", 0))
                return (409, {}, shaped)
            return contract_response(exc)
        return (200, {}, {"version": 1, "review": public})

    def _post_approve(
        self, user_id: str, role: str, job_id: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, dict[str, str], Any]:
        if role not in APPROVE_ROLES:
            return err(403, "forbidden", "forbidden")
        if not json_only(headers):
            return err(422, "invalid_schema", "json body required")
        try:
            payload = strict_dict(body)
        except ValueError:
            return err(422, "invalid_schema", "body is not strict json")
        if set(payload.keys()) != {"revision", "patientConfirmed"}:
            return err(422, "invalid_schema", "approval fields invalid")
        if not is_int(payload.get("revision")) or payload.get("patientConfirmed") is not True:
            return err(422, "invalid_schema", "approval fields invalid")
        revision = int(payload["revision"])
        gate = self._guarded(user_id, job_id)
        if gate is not None:
            return gate
        if self._authorize_approve is not None:
            try:
                allowed = bool(self._authorize_approve(user_id))
            except (OSError, ValueError, RuntimeError):
                return err(503, "unavailable", "authorization unavailable")
            if not allowed:
                return err(403, "forbidden", "forbidden")
        try:
            ready = bool(self._import_ready() if self._import_ready is not None else False)
        except (OSError, ValueError, RuntimeError):
            return err(503, "unavailable", "import unavailable")
        if not ready:
            return err(503, "not_configured", "import is not configured")
        if self._importer is None:
            return err(503, "not_configured", "import is not configured")
        if not self._gate.acquire(blocking=False):
            return err(429, "import_busy", "import is busy")
        try:
            try:
                claimed = self._reviews.claim_import(job_id, user_id, revision, True)
            except ContractError as exc:
                if str(getattr(exc, "code", "")) == "conflict":
                    try:
                        current = self._reviews.get(job_id, user_id)
                    except ContractError:
                        return contract_response(exc)
                    shaped2: Any = {
                        "version": 1,
                        "error": {"code": "conflict", "message": str(exc.message)},
                    }
                    shaped2["error"]["currentRevision"] = int(current.get("revision", 0))
                    return (409, {}, shaped2)
                return contract_response(exc)
            if bool(claimed.get("alreadyImported", False)) is True:
                try:
                    public = self._reviews.get(job_id, user_id)
                except ContractError as exc:
                    return contract_response(exc)
                return (200, {}, {"version": 1, "review": public})
            prepared = claimed.get("prepared")
            approval = str(claimed.get("approvalId", ""))
            if not isinstance(prepared, dict) or not approval:
                try:
                    self._reviews.record_failure(
                        job_id, approval or "unknown", "bad_claim", uncertain=True
                    )
                except ContractError:
                    pass
                return err(503, "unavailable", "import unavailable")
            try:
                receipt = self._importer(job_id, user_id, dict(prepared))
            except AuthError:
                try:
                    self._reviews.record_failure(job_id, approval, "auth_failed", uncertain=False)
                except ContractError:
                    pass
                return err(403, "forbidden", "forbidden")
            except ContractError as exc:
                try:
                    self._reviews.record_failure(
                        job_id, approval, str(exc.code or "invalid_candidate")[:64], uncertain=False
                    )
                except ContractError:
                    pass
                return contract_response(exc)
            except (
                TransportError,
                TimeoutError,
                OSError,
                ValueError,
                KeyError,
                RuntimeError,
            ) as exc:
                try:
                    self._reviews.record_failure(
                        job_id, approval, "import_uncertain", uncertain=True
                    )
                except ContractError:
                    pass
                _ = exc
                return err(503, "unavailable", "import uncertain")
            if not isinstance(receipt, dict):
                try:
                    self._reviews.record_failure(
                        job_id, approval, "import_uncertain", uncertain=True
                    )
                except ContractError:
                    pass
                return err(503, "unavailable", "import uncertain")
            try:
                done = self._reviews.record_import(job_id, approval, dict(receipt))
            except ContractError as exc:
                return contract_response(exc)
            return (200, {}, {"version": 1, "review": done})
        finally:
            self._gate.release()
