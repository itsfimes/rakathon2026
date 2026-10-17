from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from rakathon_backend.uploads.worker_progress import drain_progress

if TYPE_CHECKING:
    from rakathon_backend.uploads.store import UploadStore

CONVERTER_TIMEOUT = 310.0
POLL_INTERVAL = 0.2


def image_available(image: str) -> bool:
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def invoke_docker(
    store: UploadStore,
    src: Path,
    out_dir: Path,
    allow_azure: bool,
    job_id: str,
    image: str,
    provider: str,
    model: str,
    cache_path: Path | None,
    secret: str | None,
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(out_dir, 0o700)
    except OSError:
        pass
    cmd = [
        os.environ.get("PYTHON_BIN", "python3"),
        "-c",
        "from scripts.run_converter import main; raise SystemExit(main())",
        "--input",
        str(src),
        "--output",
        str(out_dir),
        "--image",
        image,
        "--no-build",
        "--provider-id",
        provider,
        "--model",
        model,
    ]
    if cache_path is not None:
        cmd += ["--recipe-cache", str(cache_path)]
    if allow_azure and secret:
        cmd += ["--allow-azure", "--secret-file", secret]
    else:
        cmd += ["--offline"]
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
        )
    except OSError:
        store.finish(job_id, "failed", {"reason": "launcher_failed"})
        return 2
    assert proc.stdout is not None and proc.stderr is not None
    start = time.monotonic()
    code: int | None = None
    while True:
        try:
            code = proc.wait(timeout=POLL_INTERVAL)
            break
        except subprocess.TimeoutExpired:
            drain_progress(store, job_id, out_dir)
            if time.monotonic() - start > CONVERTER_TIMEOUT:
                try:
                    os.killpg(proc.pid, 15)
                except (OSError, ProcessLookupError):
                    pass
                try:
                    code = proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, 9)
                    except (OSError, ProcessLookupError):
                        pass
                    proc.wait(timeout=5)
                    code = 2
                store.finish(job_id, "failed", {"reason": "converter_timeout"})
                try:
                    proc.stdout.read()
                    proc.stderr.read()
                except OSError:
                    pass
                return 2
    try:
        proc.stdout.read()
        proc.stderr.read()
    except OSError:
        pass
    return int(code) if code is not None else 2
