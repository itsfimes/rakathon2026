from __future__ import annotations

import re
import urllib.parse as _up
from collections.abc import Callable
from typing import Any

from rakathon_backend.common.errors import ContractError
from rakathon_backend.uploads.shapes import binary_envelope as _binary
from rakathon_backend.uploads.shapes import job_shape as _job_shape
from rakathon_backend.uploads.store import MAX_FILE_BYTES, UploadStore
from rakathon_backend.uploads.store_io import sanitize_filename
from rakathon_backend.uploads.worker import UploadWorker
from rakathon_backend.web.projection import ID

UPLOAD_ROLES = frozenset({"admin", "coordinator", "clinician"})
UUID_RE = re.compile(r"^[0-9a-fA-F]{32}$")
CASE_PREFIX = "/api/v1/cases/"
UPLOADS_PATH = "/api/v1/uploads"
CAPS_PATH = "/api/v1/uploads/capabilities"


class UploadRoutes:
    def __init__(
        self,
        store: UploadStore | None,
        worker: UploadWorker | None,
        *,
        authorize: Callable[[str, str], bool] | None = None,
        case_access: Callable[[str, str], bool | None] | None = None,
        ai_available: Callable[[], bool] | None = None,
    ) -> None:
        self._store = store
        self._worker = worker
        self._authorize = authorize
        self._case_access = case_access
        self._ai_available = ai_available

    def enabled(self) -> bool:
        return self._store is not None and self._worker is not None

    def _ai(self) -> bool:
        try:
            return bool(self._ai_available() if self._ai_available else False)
        except (OSError, ValueError, RuntimeError):
            return False

    def capabilities(self, role: str) -> tuple[int, dict[str, str], dict[str, Any]]:
        if not self.enabled():
            return (
                200,
                {},
                {
                    "version": 1,
                    "enabled": False,
                    "maxFileBytes": MAX_FILE_BYTES,
                    "reason": "converter_disabled",
                    "aiAvailable": False,
                },
            )
        assert self._store is not None
        if role not in UPLOAD_ROLES:
            return (
                200,
                {},
                {
                    "version": 1,
                    "enabled": False,
                    "maxFileBytes": MAX_FILE_BYTES,
                    "reason": "forbidden_role",
                    "aiAvailable": False,
                },
            )
        ai = self._ai()
        return (
            200,
            {},
            {
                "version": 1,
                "enabled": True,
                "maxFileBytes": MAX_FILE_BYTES,
                "reason": None,
                "aiAvailable": ai,
            },
        )

    def is_upload_path(self, path: str) -> bool:
        if path == CAPS_PATH:
            return True
        if path.startswith(CASE_PREFIX) and path.endswith("/uploads"):
            return True
        return bool(path.startswith(UPLOADS_PATH + "/"))

    def handle(
        self,
        user_id: str,
        role: str,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> tuple[int, dict[str, str], Any] | None:
        if not self.is_upload_path(path):
            return None
        if path == CAPS_PATH and method == "GET":
            return self.capabilities(role)
        if method == "POST" and path.startswith(CASE_PREFIX) and path.endswith("/uploads"):
            return self._post_upload(user_id, role, path, headers, body)
        if method == "GET" and path.startswith(CASE_PREFIX) and path.endswith("/uploads"):
            return self._list_case(user_id, path)
        if method == "GET" and path.startswith(UPLOADS_PATH + "/"):
            rest = path[len(UPLOADS_PATH) + 1 :]
            if "/" not in rest:
                return self._get_meta(user_id, rest)
            job_id, _, tail = rest.partition("/")
            if tail == "original" and method == "GET":
                return self._get_original(user_id, job_id)
            if tail == "export" and method == "GET":
                return self._get_export(user_id, job_id)
            return (404, {}, {"version": 1, "error": {"code": "not_found", "message": "not found"}})
        return (405, {}, {"version": 1, "error": {"code": "method_not_allowed", "message": "nope"}})

    def _check_role(self, role: str) -> tuple[int, dict[str, str], dict[str, Any]] | None:
        if role not in UPLOAD_ROLES:
            return (403, {}, {"version": 1, "error": {"code": "forbidden", "message": "forbidden"}})
        return None

    def _fresh_access(
        self, user_id: str, case_id: str
    ) -> tuple[int, dict[str, str], dict[str, Any]] | None:
        if self._authorize is not None and not self._authorize(user_id, "document.upload"):
            return (404, {}, {"version": 1, "error": {"code": "not_found", "message": "not found"}})
        if self._case_access is not None:
            try:
                allowed = self._case_access(user_id, case_id)
            except (OSError, ValueError, RuntimeError):
                allowed = None
            if allowed is False:
                return (
                    404,
                    {},
                    {"version": 1, "error": {"code": "not_found", "message": "case not found"}},
                )
            if allowed is None:
                return (
                    503,
                    {},
                    {"version": 1, "error": {"code": "unavailable", "message": "case unavailable"}},
                )
        return None

    def _post_upload(
        self, user_id: str, role: str, path: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, dict[str, str], Any]:
        denied = self._check_role(role)
        if denied is not None:
            return denied
        if not self.enabled() or self._store is None or self._worker is None:
            return (
                503,
                {},
                {"version": 1, "error": {"code": "unavailable", "message": "converter disabled"}},
            )
        assert self._store is not None
        case_id = path[len(CASE_PREFIX) : -len("/uploads")]
        if ID.fullmatch(case_id) is None or "/" in case_id or not case_id:
            return (
                400,
                {},
                {"version": 1, "error": {"code": "bad_request", "message": "bad case id"}},
            )
        ctype = headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype != "application/octet-stream":
            return (
                400,
                {},
                {
                    "version": 1,
                    "error": {"code": "bad_request", "message": "octet-stream required"},
                },
            )
        raw_name = headers.get("x-upload-name", "")
        if not raw_name:
            return (
                400,
                {},
                {"version": 1, "error": {"code": "bad_request", "message": "filename required"}},
            )
        try:
            filename = sanitize_filename(raw_name)
        except ContractError:
            return (
                400,
                {},
                {"version": 1, "error": {"code": "bad_request", "message": "filename invalid"}},
            )
        if body is None or not body:
            return (
                400,
                {},
                {"version": 1, "error": {"code": "bad_request", "message": "empty upload"}},
            )
        if len(body) > MAX_FILE_BYTES:
            return (
                413,
                {},
                {"version": 1, "error": {"code": "too_large", "message": "file exceeds 5MiB"}},
            )
        gate = self._fresh_access(user_id, case_id)
        if gate is not None:
            return gate
        try:
            job = self._store.enqueue(user_id, case_id, filename, body)
        except ContractError as exc:
            code = str(getattr(exc, "code", "bad_request"))
            if code == "too_large":
                return (
                    413,
                    {},
                    {"version": 1, "error": {"code": "too_large", "message": "file exceeds 5MiB"}},
                )
            if code == "busy":
                return (429, {}, {"version": 1, "error": {"code": "busy", "message": "queue full"}})
            if code == "store_unavailable":
                return (
                    503,
                    {},
                    {
                        "version": 1,
                        "error": {"code": "unavailable", "message": "store unavailable"},
                    },
                )
            return (
                400,
                {},
                {"version": 1, "error": {"code": "bad_request", "message": "upload rejected"}},
            )
        self._worker.submit(str(job["id"]))
        return (202, {}, _job_shape(job, self._ai()))

    def _owned(self, user_id: str, job_id: str) -> dict[str, Any] | None:
        if self._store is None or UUID_RE.match(job_id) is None:
            return None
        job = self._store.get(job_id.lower())
        if job is None or job.get("owner") != user_id:
            return None
        return job

    def _guarded(
        self, user_id: str, job_id: str
    ) -> tuple[dict[str, Any] | None, tuple[int, dict[str, str], Any] | None]:
        job = self._owned(user_id, job_id)
        if job is None:
            return (
                None,
                (404, {}, {"version": 1, "error": {"code": "not_found", "message": "not found"}}),
            )
        gate = self._fresh_access(user_id, str(job.get("caseId", "")))
        if gate is not None:
            return (None, gate)
        return (job, None)

    def _get_meta(self, user_id: str, job_id: str) -> tuple[int, dict[str, str], Any]:
        job, err = self._guarded(user_id, job_id)
        if job is None:
            assert err is not None
            out: tuple[int, dict[str, str], Any] = err
            return out
        return (200, {}, _job_shape(job, self._ai()))

    def _get_original(self, user_id: str, job_id: str) -> tuple[int, dict[str, str], Any]:
        job, err = self._guarded(user_id, job_id)
        if job is None or self._store is None:
            assert err is not None
            out2: tuple[int, dict[str, str], Any] = err
            return out2
        data = self._store.read_original(job_id.lower())
        if data is None:
            return (404, {}, {"version": 1, "error": {"code": "not_found", "message": "not found"}})
        quoted = _up.quote(str(job.get("filename", "original.bin")), safe="")
        return _binary(
            200, data, "application/octet-stream", f"attachment; filename*=UTF-8''{quoted}"
        )

    def _get_export(self, user_id: str, job_id: str) -> tuple[int, dict[str, str], Any]:
        job, err = self._guarded(user_id, job_id)
        if job is None or self._store is None:
            assert err is not None
            out3: tuple[int, dict[str, str], Any] = err
            return out3
        blob = self._store.export_zip(job_id.lower())
        if blob is None:
            return (404, {}, {"version": 1, "error": {"code": "not_found", "message": "not found"}})
        return _binary(200, blob, "application/zip", f'attachment; filename="{job_id.lower()}.zip"')

    def _list_case(self, user_id: str, path: str) -> tuple[int, dict[str, str], Any]:
        if self._store is None:
            return (
                503,
                {},
                {"version": 1, "error": {"code": "unavailable", "message": "converter disabled"}},
            )
        case_id = path[len(CASE_PREFIX) : -len("/uploads")]
        if ID.fullmatch(case_id) is None or "/" in case_id or not case_id:
            return (
                400,
                {},
                {"version": 1, "error": {"code": "bad_request", "message": "bad case id"}},
            )
        gate = self._fresh_access(user_id, case_id)
        if gate is not None:
            return gate
        jobs = self._store.list_for(user_id, case_id)
        ai = self._ai()
        return (200, {}, {"version": 1, "jobs": [_job_shape(j, ai)["job"] for j in jobs]})
