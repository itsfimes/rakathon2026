from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _parent_is_private(path: Path) -> bool:
    try:
        info = path.stat()
    except OSError:
        return False
    if info.st_uid != os.getuid():
        return False
    return (info.st_mode & 0o077) == 0


def write_client_config(
    runtime_dir: Path, tokens: dict[str, str], ai_mode: str, mode: str = "mock"
) -> Path:
    target_dir = Path(runtime_dir)
    existed = target_dir.exists()
    target_dir.mkdir(parents=True, exist_ok=True)
    if existed and not _parent_is_private(target_dir):
        raise PermissionError("runtime dir must be private")
    if not existed:
        os.chmod(target_dir, 0o700)
        if not _parent_is_private(target_dir):
            raise PermissionError("runtime dir must be private")
    path = target_dir / "demo-client.json"
    if path.is_symlink():
        raise PermissionError("client config must not be a symlink")
    if path.exists() and not _parent_is_private(path):
        raise PermissionError("client config must be private")
    body: dict[str, Any] = {
        "runtimeDir": str(target_dir),
        "tokens": dict(tokens),
        "mode": mode,
        "aiMode": ai_mode,
        "privilegedLocalDemoOnly": True,
    }
    raw = json.dumps(body).encode("utf-8")
    tmp = target_dir / f".demo-client.{os.getpid()}.tmp"
    if tmp.is_symlink():
        raise PermissionError("client config must not be a symlink")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return path


def remove_client_config(runtime_dir: Path) -> None:
    path = Path(runtime_dir) / "demo-client.json"
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
