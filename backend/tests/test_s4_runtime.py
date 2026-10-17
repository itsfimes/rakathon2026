from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

import pytest

from rakathon_backend.common.contracts import DataKind
from rakathon_backend.common.rpc import new_envelope
from rakathon_backend.runtime import commands as cmd_module
from rakathon_backend.runtime.application import BackendApp, fresh_tokens
from rakathon_backend.runtime.secret_config import remove_client_config, write_client_config


def test_secret_config_atomic_private(tmp_path: Path) -> None:
    path = write_client_config(tmp_path, {"frontend:admin": "tok"}, "mock")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["privilegedLocalDemoOnly"] is True
    again = write_client_config(tmp_path, {"frontend:admin": "tok2"}, "mock")
    assert again == path
    assert "tok2" in path.read_text(encoding="utf-8")
    remove_client_config(tmp_path)
    assert not path.exists()
    remove_client_config(tmp_path)


def test_secret_config_rejects_symlink(tmp_path: Path) -> None:
    link = tmp_path / "demo-client.json"
    target = tmp_path / "real.json"
    target.write_text("{}", encoding="utf-8")
    link.symlink_to(target)
    with pytest.raises(PermissionError):
        write_client_config(tmp_path, {"a": "b"}, "mock")


def test_secret_config_rejects_open_parent(tmp_path: Path) -> None:
    wide = tmp_path / "wide"
    wide.mkdir()
    os.chmod(wide, 0o755)
    with pytest.raises(PermissionError):
        write_client_config(wide, {"a": "b"}, "mock")


async def test_health_missing_config_down_no_sockets(tmp_path: Path) -> None:
    rc = await cmd_module.cmd_health(tmp_path)
    assert rc == 1
    assert list(tmp_path.glob("*.sock")) == []


async def test_health_symlink_config_down(tmp_path: Path) -> None:
    link = tmp_path / "demo-client.json"
    link.symlink_to(tmp_path / "real.json")
    (tmp_path / "real.json").write_text("{}", encoding="utf-8")
    assert await cmd_module.cmd_health(tmp_path) == 1


def _runtime_dir() -> Path:
    base = Path("/tmp/opencode")
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="raks4", dir=str(base)))


async def test_health_payload_liveness_scope() -> None:
    app = BackendApp(_runtime_dir(), fresh_tokens())
    await app.start()
    try:
        client = app.frontend_client("admin")
        req = new_envelope(
            source="frontend:admin",
            target="b4",
            action="health",
            data_kind=DataKind.METADATA,
            payload={},
            user_id="admin",
        )
        reply = await client.call(req, expect_source="b4")
        assert reply.payload["healthy"] is True
        assert reply.payload["scope"] == "liveness"
        assert reply.payload["deps"] == "not_checked"
    finally:
        await app.close()
