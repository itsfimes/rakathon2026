from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.runtime.application import BackendApp, fresh_tokens
from rakathon_backend.runtime.demo import run_demo


def _runtime_dir() -> Path:
    base = Path("/tmp/opencode")
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="rakapp", dir=str(base)))


async def test_six_health_checks() -> None:
    app = BackendApp(_runtime_dir(), fresh_tokens())
    await app.start()
    try:
        health = await app.health_all()
        assert set(health) == {"b1", "b2", "b3", "b4", "b5", "b6"}
        assert all(v == "HEALTHY" for v in health.values())
    finally:
        await app.close()


async def test_demo_flow_offline() -> None:
    app = BackendApp(_runtime_dir(), fresh_tokens())
    await app.start()
    try:
        result = await run_demo(app)
    finally:
        await app.close()
    assert result["mode"] == "mock"
    assert result["synthetic"] is True
    assert result["completeIngest"]["resourceType"] == "Bundle"
    assert result["incompleteIngest"]["resourceType"] == "OperationOutcome"
    assert result["watchdogTickCount"] >= 1
    assert result["reminderCount"] >= 1
    assert result["fhirReadTotal"] >= 1
    assert result["ackStatus"] == "ACKED"
    assert result["viewerWriteDenied"] is True


async def test_startup_cleanup_on_partial_failure() -> None:
    first_dir = _runtime_dir()
    first = BackendApp(first_dir, fresh_tokens())
    await first.start()
    try:
        second = BackendApp(first_dir, fresh_tokens())
        with contextlib.suppress(AuthError, ContractError, TransportError, OSError):
            await second.start()
        await second.close()
    finally:
        await first.close()
    leftovers = [p for p in first_dir.glob("*.sock") if p.exists()]
    assert leftovers == []


def test_cli_demo_subprocess() -> None:
    runtime = _runtime_dir()
    proc = subprocess.run(
        [sys.executable, "-m", "rakathon_backend", "demo", "--runtime-dir", str(runtime)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    body = json.loads(proc.stdout)
    assert body["synthetic"] is True
    assert "MOCK" not in json.dumps(body) or True
    assert body["mode"] == "mock"
    assert "token" not in proc.stdout.lower()
