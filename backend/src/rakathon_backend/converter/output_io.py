from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from rakathon_backend.converter.model_draft import MAX_DRAFT_READ_BYTES, MODEL_DRAFT_FILENAME


class OutputError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _atomic_write(path: Path, payload: bytes) -> None:
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    except OSError as exc:
        raise OutputError("output_write", "output artifact cannot be written") from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise OutputError("output_write", "output artifact cannot be written") from exc
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def write_outputs(
    outdir: Path, result: dict[str, Any], bundle: dict[str, Any] | None, provenance: dict[str, Any]
) -> None:
    if outdir.is_symlink():
        raise OutputError("output_symlink", "output directory is a symlink")
    if outdir.exists():
        if not outdir.is_dir():
            raise OutputError("output_not_dir", "output path is not a directory")
        try:
            existing = [p for p in outdir.iterdir() if p.name != "progress.json"]
            if existing:
                raise OutputError("output_not_empty", "output directory is not empty")
        except OSError as exc:
            raise OutputError("output_unreadable", "output directory cannot be read") from exc
    else:
        try:
            outdir.mkdir(parents=True, mode=0o700)
        except OSError as exc:
            raise OutputError("output_mkdir", "output directory cannot be created") from exc
        try:
            os.chmod(outdir, 0o700)
        except OSError:
            pass
    _atomic_write(outdir / "result.json", json.dumps(result, indent=2).encode("utf-8"))
    _atomic_write(outdir / "provenance.json", json.dumps(provenance, indent=2).encode("utf-8"))
    if bundle is not None:
        _atomic_write(outdir / "bundle.json", json.dumps(bundle, indent=2).encode("utf-8"))


def write_model_draft(outdir: Path, draft: dict[str, Any]) -> None:
    if outdir.is_symlink():
        raise OutputError("output_symlink", "output directory is a symlink")
    if not outdir.is_dir():
        raise OutputError("output_not_dir", "output path is not a directory")
    payload = json.dumps(draft, indent=2).encode("utf-8")
    if len(payload) > MAX_DRAFT_READ_BYTES:
        raise OutputError("output_write", "output artifact cannot be written")
    _atomic_write(outdir / MODEL_DRAFT_FILENAME, payload)
