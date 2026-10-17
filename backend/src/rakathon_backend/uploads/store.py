from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from rakathon_backend.common.errors import ContractError
from rakathon_backend.converter.detect import magic_category
from rakathon_backend.uploads.crypto import UploadKeys, load_key_file, open_sealed, seal
from rakathon_backend.uploads.store_export import build_export_zip
from rakathon_backend.uploads.store_index import (
    mark_interrupted_jobs,
    read_saved_jobs,
    scan_meta_jobs,
)
from rakathon_backend.uploads.store_io import atomic_write, now_iso, sanitize_filename, valid_uuid

__all__ = ["sanitize_filename"]

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_QUEUE_GLOBAL = 4
MAX_PER_USER = 2
STATUSES = frozenset(
    {"queued", "running", "complete", "manual-review", "failed", "cancelled", "interrupted"}
)


class UploadStore:
    def __init__(self, store_dir: Path, keys: UploadKeys) -> None:
        self._dir = store_dir
        self._keys = keys
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        if store_dir.is_symlink():
            raise ContractError(code="store_unavailable", message="upload store unavailable")
        store_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        try:
            os.chmod(store_dir, 0o700)
        except OSError:
            pass
        self._load_index()
        self._mark_interrupted()

    @staticmethod
    def open(store_dir: Path, key_file: Path) -> UploadStore:
        return UploadStore(store_dir, load_key_file(key_file))

    @property
    def root(self) -> Path:
        return self._dir

    def _index_path(self) -> Path:
        return self._dir / "index.json"

    def _job_dir(self, job_id: str) -> Path:
        return self._dir / job_id

    def _aad(self, job_id: str, purpose: str) -> bytes:
        return f"upload:{job_id}:{purpose}:v1".encode()

    def _load_index(self) -> None:
        jobs = read_saved_jobs(self._index_path())
        if jobs:
            self._jobs.update(jobs)
        else:
            self._recover_from_meta()

    def _recover_from_meta(self) -> None:
        for name, job in scan_meta_jobs(self._dir).items():
            if name not in self._jobs:
                self._jobs[name] = job

    def _save_index(self) -> None:
        payload = json.dumps(self._jobs, indent=2).encode("utf-8")
        atomic_write(self._index_path(), payload)

    def _write_meta_locked(self, job: dict[str, Any]) -> None:
        atomic_write(
            self._job_dir(str(job.get("id", ""))) / "meta.json",
            json.dumps(job, indent=2).encode("utf-8"),
        )

    def _mark_interrupted(self) -> None:
        if not mark_interrupted_jobs(self._jobs):
            return
        try:
            self._save_index()
        except OSError:
            pass

    def _counts(self) -> tuple[int, dict[str, int]]:
        queued = sum(1 for j in self._jobs.values() if j.get("status") in ("queued", "running"))
        per: dict[str, int] = {}
        for job in self._jobs.values():
            if job.get("status") in ("queued", "running"):
                owner = str(job.get("owner", ""))
                per[owner] = per.get(owner, 0) + 1
        return (queued, per)

    def enqueue(self, owner: str, case_id: str, filename: str, data: bytes) -> dict[str, Any]:
        if not owner or not case_id or len(case_id) > 128:
            raise ContractError(code="bad_request", message="upload rejected")
        if not data or len(data) > MAX_FILE_BYTES:
            raise ContractError(code="too_large", message="file exceeds the size cap")
        if len(filename) > 128:
            raise ContractError(code="bad_request", message="filename invalid")
        with self._lock:
            queued, per = self._counts()
            if queued >= MAX_QUEUE_GLOBAL:
                raise ContractError(code="busy", message="upload queue is full")
            if per.get(owner, 0) >= MAX_PER_USER:
                raise ContractError(code="busy", message="per-user queue is full")
            job_id = uuid.uuid4().hex
            sha = hashlib.sha256(data).hexdigest()
            category, magic = magic_category(data)
            detected = f"{category}/{magic}"
            nonce, ct = seal(self._keys.key, self._aad(job_id, "original"), data)
            job_dir = self._job_dir(job_id)
            if job_dir.is_symlink():
                raise ContractError(code="store_unavailable", message="upload store unavailable")
            job_dir.mkdir(mode=0o700, exist_ok=True)
            atomic_write(job_dir / "original.bin", nonce + b"." + base64.b64encode(ct))
            job: dict[str, Any] = {
                "id": job_id,
                "caseId": case_id,
                "owner": owner,
                "filename": filename,
                "sha256": sha,
                "sourceUrn": f"urn:sha256:{sha}",
                "detectedType": detected,
                "status": "queued",
                "createdAt": now_iso(),
                "events": [{"code": "queued", "status": "ok", "at": now_iso()}],
                "counts": {},
                "recipeReuse": False,
                "newFormat": False,
                "plannerMode": "none",
            }
            self._jobs[job_id] = job
            try:
                self._write_meta_locked(job)
                self._save_index()
            except OSError as exc:
                self._jobs.pop(job_id, None)
                raise ContractError(
                    code="store_unavailable", message="upload store unavailable"
                ) from exc
            return dict(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        if not valid_uuid(job_id):
            return None
        with self._lock:
            job = self._jobs.get(job_id.lower())
            return dict(job) if job is not None else None

    def list_for(self, owner: str, case_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            out = [dict(j) for j in self._jobs.values() if j.get("owner") == owner]
        if case_id is not None:
            out = [j for j in out if j.get("caseId") == case_id]
        out.sort(key=lambda j: str(j.get("createdAt", "")))
        return out

    def claim_specific(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id.lower())
            if job is None or job.get("status") != "queued":
                return None
            job["status"] = "running"
            events = job.get("events")
            if isinstance(events, list):
                events.append({"code": "running", "status": "ok", "at": now_iso()})
            try:
                self._save_index()
            except OSError:
                job["status"] = "queued"
                raise
            return dict(job)

    def claim_next(self) -> dict[str, Any] | None:
        with self._lock:
            running = any(j.get("status") == "running" for j in self._jobs.values())
            if running:
                return None
            cands = [j for j in self._jobs.values() if j.get("status") == "queued"]
            if not cands:
                return None
            cands.sort(key=lambda j: str(j.get("createdAt", "")))
            job = cands[0]
            job["status"] = "running"
            events = job.get("events")
            if isinstance(events, list):
                events.append({"code": "running", "status": "ok", "at": now_iso()})
            try:
                self._save_index()
            except OSError:
                job["status"] = "queued"
                raise
            return dict(job)

    def mark_unknown(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["newFormat"] = True
            events = job.get("events")
            if (
                isinstance(events, list)
                and len(events) < 64
                and not any(
                    isinstance(e, dict) and e.get("code") == "new_format_detected" for e in events
                )
            ):
                events.append({"code": "new_format_detected", "status": "ok", "at": now_iso()})
            try:
                self._save_index()
            except OSError:
                pass

    def finish(self, job_id: str, status: str, patch: dict[str, Any] | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["status"] = status
            if patch:
                for key in (
                    "counts",
                    "recipeReuse",
                    "newFormat",
                    "plannerMode",
                    "issues",
                    "fhirStatus",
                    "reason",
                    "modelMode",
                ):
                    if key in patch:
                        job[key] = patch[key]
            events = job.get("events")
            if isinstance(events, list):
                events.append({"code": status, "status": "ok", "at": now_iso()})
            try:
                self._save_index()
                self._write_meta_locked(job)
            except OSError:
                pass

    def append_event(self, job_id: str, code: str, status: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            events = job.get("events")
            if (
                isinstance(events, list)
                and len(events) < 64
                and not any(
                    isinstance(e, dict) and e.get("code") == code and e.get("status") == status
                    for e in events[-8:]
                )
            ):
                events.append({"code": code[:64], "status": status[:32], "at": now_iso()})
            try:
                self._save_index()
            except OSError:
                pass

    def cancel(self, job_id: str, owner: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.get("owner") != owner or job.get("status") != "queued":
                return False
            job["status"] = "cancelled"
            try:
                self._save_index()
                self._write_meta_locked(job)
            except OSError:
                job["status"] = "queued"
                try:
                    self._save_index()
                except OSError:
                    pass
                return False
            return True

    def read_original(self, job_id: str) -> bytes | None:
        job = self.get(job_id)
        if job is None:
            return None
        try:
            blob = (self._job_dir(job_id) / "original.bin").read_bytes()
        except OSError:
            return None
        try:
            nonce_b, ct_b = blob.rsplit(b".", 1)
            ct = base64.b64decode(ct_b)
        except ValueError:
            return None
        try:
            plain = open_sealed(self._keys.key, self._aad(job_id, "original"), nonce_b, ct)
        except ContractError:
            return None
        if hashlib.sha256(plain).hexdigest() != str(job.get("sha256", "")):
            return None
        return plain

    def write_result_blob(self, job_id: str, name: str, payload: bytes) -> None:
        nonce, ct = seal(self._keys.key, self._aad(job_id, name), payload)
        atomic_write(self._job_dir(job_id) / f"{name}.enc", nonce + b"." + base64.b64encode(ct))

    def read_result_blob(self, job_id: str, name: str) -> bytes | None:
        try:
            blob = (self._job_dir(job_id) / f"{name}.enc").read_bytes()
        except OSError:
            return None
        try:
            nonce_b, ct_b = blob.rsplit(b".", 1)
            ct = base64.b64decode(ct_b)
        except ValueError:
            return None
        try:
            return open_sealed(self._keys.key, self._aad(job_id, name), nonce_b, ct)
        except ContractError:
            return None

    def export_zip(self, job_id: str) -> bytes | None:
        job = self.get(job_id)
        if job is None:
            return None
        original = self.read_original(job_id)
        if original is None:
            return None
        return build_export_zip(
            original,
            self.read_result_blob(job_id, "result"),
            self.read_result_blob(job_id, "bundle"),
            self.read_result_blob(job_id, "provenance"),
            job.get("events", []),
            job.get("status"),
            job.get("sha256"),
        )
