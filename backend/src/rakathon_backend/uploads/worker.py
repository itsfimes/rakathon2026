from __future__ import annotations

import concurrent.futures as _fut
import hashlib
import os
import shutil
import stat
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rakathon_backend.common.errors import ContractError
from rakathon_backend.converter.detect import magic_category
from rakathon_backend.converter.planner import RecipeCache
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.uploads.suffix import SAFE_SUFFIXES
from rakathon_backend.uploads.suffix import safe_suffix as _safe_suffix
from rakathon_backend.uploads.worker_collect import collect_result
from rakathon_backend.uploads.worker_docker import image_available, invoke_docker
from rakathon_backend.uploads.worker_progress import drain_progress


class UploadWorker:
    def __init__(
        self,
        store: UploadStore,
        *,
        secret_file: str | None = None,
        image: str = "rakathon-converter:latest",
        provider: str = "rakathon-azure",
        model: str = "gpt-6-luna-dz-eu",
        recipe_cache: Path | None = None,
        runner: Callable[..., int] | None = None,
    ) -> None:
        self._store = store
        self._secret = secret_file
        self._image = image
        self._provider = provider
        self._model = model
        self._pool = _fut.ThreadPoolExecutor(max_workers=1, thread_name_prefix="upload-conv")
        self._lock = threading.Lock()
        self._pending: set[str] = set()
        self._cache = RecipeCache(recipe_cache)
        self._runner = runner

    def cache_path(self) -> Path | None:
        return getattr(self._cache, "_path", None)

    def submit(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._pending:
                return
            self._pending.add(job_id)
        self._pool.submit(self._run_job, job_id)

    def _run_job(self, job_id: str) -> None:
        try:
            try:
                claimed: dict[str, Any] | None = self._store.claim_specific(job_id)
            except (ContractError, OSError, ValueError, RuntimeError):
                try:
                    self._store.finish(job_id, "failed", {"reason": "store_unavailable"})
                except (ContractError, OSError, ValueError, RuntimeError, KeyError):
                    pass
                return
            if claimed is None:
                job = self._store.get(job_id)
                if job is not None and job.get("status") == "queued":
                    self._store.append_event(job_id, "busy", "deferred")
                return
            target = str(claimed.get("id", job_id))
            try:
                self._convert(target)
            except ContractError:
                self._store.finish(target, "failed", {"reason": "store_unavailable"})
            except (OSError, ValueError, RuntimeError, KeyError):
                self._store.finish(target, "failed", {"reason": "internal_error"})
        finally:
            with self._lock:
                self._pending.discard(job_id)

    def _convert(self, job_id: str) -> None:
        job = self._store.get(job_id)
        if job is None:
            return
        original = self._store.read_original(job_id)
        if original is None:
            self._store.finish(job_id, "failed", {"reason": "original_unavailable"})
            return
        if hashlib.sha256(original).hexdigest() != str(job.get("sha256", "")):
            self._store.finish(job_id, "failed", {"reason": "sha_mismatch"})
            return
        filename = str(job.get("filename", "input.bin"))
        suffix = _safe_suffix(filename, original)
        base = Path(tempfile.mkdtemp(prefix="up-job-"))
        try:
            os.chmod(base, 0o700)
            tmp_in = base / "in"
            tmp_out = base / "out"
            tmp_in.mkdir(mode=0o700)
            tmp_out.mkdir(mode=0o700)
            src = tmp_in / f"input{suffix}"
            src.write_bytes(original)
            os.chmod(src, 0o600)
            out_dir = tmp_out / "result"
            out_dir.mkdir(mode=0o700, exist_ok=True)
            detected_unknown = suffix not in SAFE_SUFFIXES or suffix == ".bin"
            if detected_unknown:
                self._store.mark_unknown(job_id)
            else:
                category, _magic = magic_category(original)
                if suffix == ".bin" and category in ("text", "binary", "zip", "rtf", "html", "xml"):
                    self._store.mark_unknown(job_id)
            allow_azure = bool(self._secret)
            code = self._invoke(src, out_dir, allow_azure, job_id)
            drain_progress(self._store, job_id, out_dir)
            collect_result(self._store, self._cache, allow_azure, job_id, out_dir, code)
        except (OSError, ValueError, RuntimeError):
            self._store.finish(job_id, "failed", {"reason": "convert_error"})
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def _invoke(self, src: Path, out_dir: Path, allow_azure: bool, job_id: str) -> int:
        if self._runner is not None:
            try:
                return int(self._runner(src, out_dir, allow_azure))
            except (OSError, ValueError, RuntimeError, TypeError):
                return 2
        if shutil.which("docker") is None or not image_available(self._image):
            self._store.finish(job_id, "failed", {"reason": "no_docker"})
            return 2
        return invoke_docker(
            self._store,
            src,
            out_dir,
            allow_azure,
            job_id,
            self._image,
            self._provider,
            self._model,
            self.cache_path(),
            self._secret,
        )

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def launcher_secret_ok(secret_file: str | None) -> bool:
    if not secret_file:
        return False
    try:
        st = Path(secret_file).stat()
    except OSError:
        return False
    return bool(stat.S_ISREG(st.st_mode) and (st.st_mode & 0o077) == 0)
