from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import pytest

import rakathon_backend.runtime.application as app_module
from rakathon_backend.b5.gateway import MockAdapter
from rakathon_backend.runtime.application import BackendApp, fresh_tokens
from rakathon_backend.runtime.demo import run_demo


def _runtime_dir() -> Path:
    base = Path("/tmp/opencode")
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="rakai", dir=str(base)))


class _FakeAdapter:
    def __init__(self) -> None:
        self.closed = False
        self.calls = 0

    async def translate(self, data: bytes, content_type: str) -> dict[str, Any]:
        _ = (data, content_type)
        self.calls += 1
        return {"answer": "fake", "mode": "direct", "synthetic": False}

    async def complete(self, data: bytes, content_type: str) -> dict[str, Any]:
        _ = (data, content_type)
        self.calls += 1
        return {"answer": "fake", "mode": "direct", "synthetic": False}

    async def close(self) -> None:
        self.closed = True


def test_bad_ai_mode_rejected() -> None:
    with pytest.raises(ValueError):
        BackendApp(_runtime_dir(), fresh_tokens(), ai_mode="remote")


def test_bad_watchdog_interval_rejected() -> None:
    with pytest.raises(ValueError):
        BackendApp(_runtime_dir(), fresh_tokens(), watchdog_interval=0.01)


async def test_injected_adapter_and_mode() -> None:
    adapter = _FakeAdapter()
    app = BackendApp(_runtime_dir(), fresh_tokens(), ai_adapter=adapter, ai_mode="direct")
    assert app.ai_mode == "direct"
    assert app.kill_switch.allow_remote is True
    await app.start()
    try:
        assert app.gateway is not None
        assert app.gateway.mode == "direct"
    finally:
        await app.close()
    assert adapter.closed is True


async def test_close_trips_gateway_and_closes_adapter() -> None:
    adapter = _FakeAdapter()
    app = BackendApp(_runtime_dir(), fresh_tokens(), ai_adapter=adapter, ai_mode="direct")
    await app.start()
    await app.close()
    assert adapter.closed is True
    assert app.gateway is not None
    assert app.gateway.switch.tripped is True


async def test_default_demo_unchanged() -> None:
    app = BackendApp(_runtime_dir(), fresh_tokens())
    await app.start()
    try:
        result = await run_demo(app)
    finally:
        await app.close()
    assert result["mode"] == "mock"
    assert result["synthetic"] is True


async def test_kill_file_monitor_trips_running_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "KILL_POLL_SECONDS", 0.05)
    kill_file = tmp_path / "kill-ai"
    adapter = _FakeAdapter()
    app = BackendApp(
        _runtime_dir(), fresh_tokens(), ai_adapter=adapter, ai_mode="direct", kill_file=kill_file
    )
    await app.start()
    try:
        assert app.gateway is not None
        assert app.gateway.switch.tripped is False
        kill_file.write_text("stop", encoding="utf-8")
        for _ in range(100):
            if app.gateway.switch.tripped:
                break
            await asyncio.sleep(0.05)
        assert app.gateway.switch.tripped is True
        assert adapter.closed is True
    finally:
        await app.close()


async def test_mock_adapter_still_default() -> None:
    app = BackendApp(_runtime_dir(), fresh_tokens())
    await app.start()
    try:
        assert app.gateway is not None
        assert app.gateway.mode == "mock"
        assert app.kill_switch.allow_remote is False
    finally:
        await app.close()


async def test_b5_shutdown_closes_adapter() -> None:
    adapter = MockAdapter()
    app = BackendApp(_runtime_dir(), fresh_tokens(), ai_adapter=adapter, ai_mode="mock")
    await app.start()
    await app.close()
    assert adapter.closed is True


async def test_ai_disabled_env_trips_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "KILL_POLL_SECONDS", 0.05)
    adapter = _FakeAdapter()
    app = BackendApp(_runtime_dir(), fresh_tokens(), ai_adapter=adapter, ai_mode="direct")
    await app.start()
    try:
        monkeypatch.setenv("AI_DISABLED", "1")
        for _ in range(100):
            assert app.gateway is not None
            if app.gateway.switch.tripped:
                break
            await asyncio.sleep(0.05)
        assert app.gateway is not None
        assert app.gateway.switch.tripped is True
    finally:
        await app.close()
