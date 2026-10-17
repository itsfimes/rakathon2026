from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import pytest

from rakathon_backend.b5.opencode import process as proc_module
from rakathon_backend.cli import build_parser
from rakathon_backend.runtime import commands as cmd_module


def _env() -> dict[str, str]:
    return {
        "RAKATHON_AI_ENABLE": "1",
        "RAKATHON_AI_OS_EGRESS_ISOLATED": "1",
        "RAKATHON_AI_PROVIDER": "local",
        "RAKATHON_AI_MODEL": "tiny",
        "RAKATHON_AI_BASE_URL": "http://127.0.0.1:11434",
    }


async def test_ai_check_reports_blockers_without_env(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for key in (
        "RAKATHON_AI_ENABLE",
        "RAKATHON_AI_OS_EGRESS_ISOLATED",
        "RAKATHON_AI_PROVIDER",
        "RAKATHON_AI_MODEL",
        "RAKATHON_AI_BASE_URL",
        "AI_DISABLED",
        "RAKATHON_AI_KILL_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RAKATHON_AI_BINARY", sys.executable)
    rc = await cmd_module.cmd_ai_check()
    assert rc == 2
    report = json.loads(capsys.readouterr().out)
    assert report["enabled"] is False
    assert len(report["blockers"]) >= 3
    assert report["binaryOk"] is False


async def test_ai_check_ready_with_fake_version(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for key, value in _env().items():
        monkeypatch.setenv(key, value)

    async def fake_probe(binary: str, expected: str, timeout: float = 10.0) -> str:
        _ = (binary, expected, timeout)
        return "2.0.31"

    monkeypatch.setattr(proc_module, "probe_version", fake_probe)
    monkeypatch.setattr(cmd_module, "probe_version", fake_probe)
    rc = await cmd_module.cmd_ai_check()
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["enabled"] is True
    assert report["binaryVersion"] == "2.0.31"


async def test_ai_check_never_spawns_server(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _env().items():
        monkeypatch.setenv(key, value)
    called: list[Any] = []

    async def fake_probe(binary: str, expected: str, timeout: float = 10.0) -> str:
        _ = (binary, expected, timeout)
        return "2.0.31"

    async def fake_spawn(*args: Any, **kwargs: Any) -> Any:
        called.append((args, kwargs))
        raise AssertionError("must not spawn")

    monkeypatch.setattr(proc_module, "probe_version", fake_probe)
    monkeypatch.setattr(cmd_module, "probe_version", fake_probe)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    rc = await cmd_module.cmd_ai_check()
    assert rc == 0
    assert called == []


def test_serve_parser_has_ai_and_watchdog() -> None:
    args = build_parser().parse_args(["serve", "--ai", "opencode", "--watchdog-interval", "2.5"])
    assert args.ai == "opencode"
    assert float(args.watchdog_interval) == 2.5
    defaults = build_parser().parse_args(["serve"])
    assert defaults.ai == "mock"
    assert float(defaults.watchdog_interval) == 1.0


def test_ai_check_parser_exists() -> None:
    args = build_parser().parse_args(["ai-check"])
    assert args.command == "ai-check"
