from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any

from rakathon_backend.common.errors import ContractError
from rakathon_backend.uploads.crypto import NONCE_SIZE, UploadKeys, open_sealed


class UploadReadMixin:
    _dir: Path
    _keys: UploadKeys
    _lock: Lock
    _jobs: dict[str, dict[str, Any]]

    def list_case(self, case_id: str, *, max_bytes: int | None = None) -> list[dict[str, Any]]:
        out = []
        size = 0
        with self._lock:
            for job in self._jobs.values():
                if job.get("caseId") != case_id:
                    continue
                if max_bytes is not None:
                    size += len(json.dumps(job, ensure_ascii=True).encode())
                    if size > max_bytes:
                        raise ContractError(
                            code="resource_limit", message="Upload context too large"
                        )
                out.append(dict(job))
        return sorted(out, key=lambda j: str(j.get("createdAt", "")))

    def read_result_blob(
        self, job_id: str, name: str, *, max_bytes: int | None = None
    ) -> bytes | None:
        limit = (
            NONCE_SIZE + 1 + 4 * ((max(0, max_bytes) + 16 + 2) // 3)
            if max_bytes is not None
            else None
        )
        try:
            with (self._dir / job_id / f"{name}.enc").open("rb") as file:
                if limit is not None and os.fstat(file.fileno()).st_size > limit:
                    raise ContractError(code="resource_limit", message="Upload context too large")
                blob = file.read(limit + 1 if limit is not None else -1)
        except OSError:
            return None
        if limit is not None and len(blob) > limit:
            raise ContractError(code="resource_limit", message="Upload context too large")
        try:
            nonce_b, ct_b = blob.rsplit(b".", 1)
            ct = base64.b64decode(ct_b)
        except ValueError:
            return None
        try:
            plain = open_sealed(self._keys.key, f"upload:{job_id}:{name}:v1".encode(), nonce_b, ct)
        except ContractError:
            return None
        if max_bytes is not None and len(plain) > max_bytes:
            raise ContractError(code="resource_limit", message="Upload context too large")
        return plain
