from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from typing import Any, Self

import httpx
import pytest

from rakathon_backend.b5.opencode import process as proc_module
from rakathon_backend.b5.opencode.process import OpenCodeProcess, probe_version
from rakathon_backend.common.errors import TransportError


class _FakeProc:
    def __init__(self, returncode: int | None = None) -> None:
        self.returncode = returncode
        self.pid = 424242
        self.killed = False
        self._waiters = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return (b"opencode v2.0.31\n", b"")

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        self._waiters += 1
        if self.returncode is None:
            self.returncode = -signal.SIGTERM
        return self.returncode


def _process(**kwargs: Any) -> OpenCodeProcess:
    defaults: dict[str, Any] = {
        "binary": "opencode",
        "expected_version": "2.0.31",
        "provider_id": "local",
        "model": "tiny",
        "provider_base_url": "http://127.0.0.1:11434",
        "startup_timeout": 5.0,
    }
    defaults.update(kwargs)
    return OpenCodeProcess(**defaults)


async def test_probe_version_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_spawn(*args: Any, **kwargs: Any) -> _FakeProc:
        _ = (args, kwargs)
        return _FakeProc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    assert await probe_version("opencode", "2.0.31") == "2.0.31"


async def test_probe_version_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Old(_FakeProc):
        async def communicate(self) -> tuple[bytes, bytes]:
            return (b"opencode v1.9.9\n", b"")

    async def fake_spawn(*args: Any, **kwargs: Any) -> _Old:
        _ = (args, kwargs)
        return _Old(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    with pytest.raises(TransportError):
        await probe_version("opencode", "2.0.31")


async def test_probe_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_spawn(*args: Any, **kwargs: Any) -> _FakeProc:
        _ = (args, kwargs)
        raise FileNotFoundError("no such binary")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    with pytest.raises(TransportError):
        await probe_version("nope-binary", "2.0.31")


async def test_start_env_isolation_and_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    os.environ["RAKATHON_SECRET_SHOULD_NOT_LEAK"] = "s3cret"
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://otel.example.com"
    captured: dict[str, Any] = {}
    fake = _FakeProc()

    async def fake_spawn(*args: Any, **kwargs: Any) -> _FakeProc:
        captured["args"] = args
        captured["env"] = dict(kwargs.get("env", {}))
        assert kwargs.get("start_new_session") is True
        return fake

    async def fake_probe(binary: str, expected: str, timeout: float = 10.0) -> str:
        _ = (binary, expected, timeout)
        return "2.0.31"

    async def fake_ready(self: OpenCodeProcess) -> None:
        _ = self

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(proc_module, "probe_version", fake_probe)
    monkeypatch.setattr(OpenCodeProcess, "_wait_ready", fake_ready)
    proc = _process()
    try:
        url = await proc.start()
        assert url.startswith("http://127.0.0.1:")
        env = captured["env"]
        assert "RAKATHON_SECRET_SHOULD_NOT_LEAK" not in env
        assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in env
        assert "OTEL_RESOURCE_ATTRIBUTES" not in env
        assert set(env) >= {
            "PATH",
            "LANG",
            "HOME",
            "XDG_CONFIG_HOME",
            "OPENCODE_CONFIG_CONTENT",
            "OPENCODE_DISABLE_PROJECT_CONFIG",
            "OPENCODE_PURE",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS",
            "OPENCODE_DISABLE_EXTERNAL_SKILLS",
            "OPENCODE_DISABLE_EMBEDDED_WEB_UI",
            "OPENCODE_DISABLE_LSP_DOWNLOAD",
            "OPENCODE_DISABLE_AUTOUPDATE",
            "OPENCODE_DISABLE_MODELS_FETCH",
            "OPENCODE_DISABLE_AUTOCOMPACT",
            "OPENCODE_DB",
            "OPENCODE_SERVER_PASSWORD",
        }
        assert len(env["OPENCODE_SERVER_PASSWORD"]) >= 32
        assert '"permission":"deny"' in env["OPENCODE_CONFIG_CONTENT"].replace(" ", "")
        scratch = Path(env["HOME"])
        assert scratch.is_dir()
        assert oct(scratch.stat().st_mode & 0o777) == "0o700"
        assert str(scratch).startswith("/tmp/opencode")
        assert list(captured["args"])[:3] == ["opencode", "serve", "--hostname=127.0.0.1"]
    finally:
        await proc.close()
        assert Path(captured["env"]["HOME"]).exists() is False
    del os.environ["RAKATHON_SECRET_SHOULD_NOT_LEAK"]
    del os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]


async def test_close_kill_escalation(monkeypatch: pytest.MonkeyPatch) -> None:
    signals: list[tuple[int, int]] = []

    class _Hanging(_FakeProc):
        async def wait(self) -> int:
            for _ in range(600):
                if (self.pid, signal.SIGKILL) in signals:
                    self.returncode = -signal.SIGKILL
                    return self.returncode
                await asyncio.sleep(0.01)
            self.returncode = -signal.SIGKILL
            return self.returncode

    fake = _Hanging()

    def fake_killpg(pgid: int, sig: int) -> None:
        signals.append((pgid, sig))

    async def fake_spawn(*args: Any, **kwargs: Any) -> _Hanging:
        _ = (args, kwargs)
        return fake

    async def fake_probe(binary: str, expected: str, timeout: float = 10.0) -> str:
        _ = (binary, expected, timeout)
        return "2.0.31"

    async def fake_ready(self: OpenCodeProcess) -> None:
        _ = self

    monkeypatch.setattr(os, "killpg", fake_killpg)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(proc_module, "probe_version", fake_probe)
    monkeypatch.setattr(OpenCodeProcess, "_wait_ready", fake_ready)
    proc = _process()
    await proc.start()
    await proc.close()
    await proc.close()
    assert (fake.pid, signal.SIGTERM) in signals
    assert (fake.pid, signal.SIGKILL) in signals


async def test_readiness_polls_api_session(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    fake = _FakeProc()

    async def fake_spawn(*args: Any, **kwargs: Any) -> _FakeProc:
        _ = (args, kwargs)
        return fake

    async def fake_probe(binary: str, expected: str, timeout: float = 10.0) -> str:
        _ = (binary, expected, timeout)
        return "2.0.31"

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _ = (args, kwargs)
            seen["auth"] = kwargs.get("auth")

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            _ = args

        async def get(self, url: str) -> _Resp:
            seen["url"] = url
            return _Resp()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(proc_module, "probe_version", fake_probe)
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    proc = _process()
    try:
        url = await proc.start()
        assert str(seen["url"]) == f"{url}/api/session"
        assert seen["auth"] is not None
    finally:
        await proc.close()


async def test_readiness_failure_closes_child(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeProc()

    async def fake_spawn(*args: Any, **kwargs: Any) -> _FakeProc:
        _ = (args, kwargs)
        return fake

    async def fake_probe(binary: str, expected: str, timeout: float = 10.0) -> str:
        _ = (binary, expected, timeout)
        return "2.0.31"

    def fail_client(*args: Any, **kwargs: Any) -> Any:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(proc_module, "probe_version", fake_probe)
    monkeypatch.setattr(httpx, "AsyncClient", fail_client)
    proc = _process(startup_timeout=0.3)
    with pytest.raises(TransportError):
        await proc.start()
    assert proc.started is False
    assert fake.returncode is not None
