from __future__ import annotations

import asyncio
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Self

import httpx
import pytest

from rakathon_backend.b5.opencode import process as proc_module
from rakathon_backend.b5.opencode.client import OpenCodeClient
from rakathon_backend.b5.opencode.process import OpenCodeProcess
from rakathon_backend.common.contracts import DataKind
from rakathon_backend.common.rpc import new_envelope
from rakathon_backend.runtime import commands as cmd_module
from rakathon_backend.runtime.application import BackendApp, fresh_tokens
from rakathon_backend.runtime.secret_config import remove_client_config, write_client_config


def _ok_handler(request: httpx.Request) -> httpx.Response:
    _ = request
    return httpx.Response(200, json={"data": {"text": "hi"}})


async def test_client_ignores_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://evil.example:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://evil.example:9")
    monkeypatch.setenv("ALL_PROXY", "http://evil.example:9")
    transport = httpx.MockTransport(_ok_handler)
    client = OpenCodeClient(
        "http://127.0.0.1:4099", "pw", "local", "tiny", timeout=5.0, transport=transport
    )
    try:
        assert client._http.trust_env is False
        assert await client.generate("ses-1", "hello") == "hi"
    finally:
        await client.aclose()


async def test_readiness_ignores_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _ = args
            seen.update(kwargs)

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            _ = args

        async def get(self, url: str) -> _Resp:
            _ = url
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    proc = OpenCodeProcess(
        binary="opencode",
        expected_version="2.0.31",
        provider_id="local",
        model="tiny",
        provider_base_url="http://127.0.0.1:11434",
        startup_timeout=5.0,
    )
    proc._base_url = "http://127.0.0.1:9"
    proc._password = "pw-value"
    await proc._wait_ready()
    assert seen.get("trust_env") is False


async def test_start_env_has_no_proxy_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_spawn(*args: Any, **kwargs: Any) -> Any:
        captured["env"] = dict(kwargs.get("env", {}))

        class _Done:
            returncode = 0
            pid = 1

            async def wait(self) -> int:
                return 0

        return _Done()

    async def fake_probe(binary: str, expected: str, timeout: float = 10.0) -> str:
        _ = (binary, expected, timeout)
        return "2.0.31"

    async def fake_ready(self: OpenCodeProcess) -> None:
        _ = self

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(proc_module, "probe_version", fake_probe)
    monkeypatch.setattr(OpenCodeProcess, "_wait_ready", fake_ready)
    proc = OpenCodeProcess(
        binary="opencode",
        expected_version="2.0.31",
        provider_id="local",
        model="tiny",
        provider_base_url="http://127.0.0.1:11434",
        startup_timeout=5.0,
    )
    try:
        await proc.start()
        env = captured["env"]
        assert "HTTP_PROXY" not in env and "HTTPS_PROXY" not in env
    finally:
        await proc.close()


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
