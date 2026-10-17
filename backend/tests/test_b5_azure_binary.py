from __future__ import annotations

import asyncio
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest

from rakathon_backend.b5.opencode import process as proc_module
from rakathon_backend.b5.opencode import validation as validation_module
from rakathon_backend.b5.opencode.client import OpenCodeClient
from rakathon_backend.b5.opencode.config import from_env
from rakathon_backend.b5.opencode.process import OpenCodeProcess, probe_version

_TEST_KEY = "offline-fake-api-key-for-header-assert"
_UNSHARE_GUARD = "RAKATHON_UNSHARE_WRAPPED"


def _binary_available() -> bool:
    if shutil.which("opencode") is None:
        return False
    try:
        proc = subprocess.run(
            ["opencode", "--version"],
            check=False,
            capture_output=True,
            timeout=15,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "opencode v2.0.31"


def _unshare_available() -> bool:
    if shutil.which("unshare") is None or shutil.which("ip") is None:
        return False
    try:
        proc = subprocess.run(
            ["unshare", "--user", "--map-root-user", "--net", "true"],
            check=False,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


class _FakeChatCompletions(http.server.BaseHTTPRequestHandler):
    seen: ClassVar[dict[str, Any]] = {}

    def do_GET(self) -> None:
        body = json.dumps({"data": [{"id": "tiny"}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0") or 0)
        if length:
            self.rfile.read(length)
        type(self).seen = {
            "headers": {key.lower(): value for key, value in dict(self.headers).items()},
            "path": self.path,
        }
        first = (
            'data: {"id":"chatcmpl-1","object":"chat.completion.chunk",'
            '"created":1,"model":"tiny","choices":[{"index":0,'
            '"delta":{"role":"assistant","content":"h"},"finish_reason":null}]}\n\n'
        )
        second = (
            'data: {"id":"chatcmpl-1","object":"chat.completion.chunk",'
            '"created":1,"model":"tiny","choices":[{"index":0,'
            '"delta":{"content":"i"},"finish_reason":null}]}\n\n'
        )
        third = (
            'data: {"id":"chatcmpl-1","object":"chat.completion.chunk",'
            '"created":1,"model":"tiny","choices":[{"index":0,'
            '"delta":{},"finish_reason":"stop"}]}\n\n'
        )
        body = (first + second + third + "data: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        _ = args


async def _run_real_binary_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await probe_version("opencode", "2.0.31") == "2.0.31"
    port = _free_port()
    fake_url = f"http://127.0.0.1:{port}"
    monkeypatch.setattr(validation_module, "AZURE_BASE_URL", fake_url)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), _FakeChatCompletions)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    process: OpenCodeProcess | None = None
    client: OpenCodeClient | None = None
    try:
        env = {
            "RAKATHON_AI_ENABLE": "1",
            "RAKATHON_AI_TRUST_AZURE": "1",
            "RAKATHON_AI_PROVIDER_KIND": "azure",
            "RAKATHON_AI_MODEL": "tiny",
            "RAKATHON_AI_BASE_URL": fake_url,
            "RAKATHON_AI_API_KEY": _TEST_KEY,
        }
        config = from_env(env, requested=True)
        assert config.ready is True
        assert config.provider_id == "rakathon-azure"
        process = OpenCodeProcess(
            config.binary,
            config.expected_version,
            config.provider_id,
            config.model,
            config.base_url,
            startup_timeout=30.0,
            api_key=_TEST_KEY,
            provider_kind=config.provider_kind,
        )
        base_url = await process.start()
        username, password = process.auth()
        assert username == "opencode"
        async with httpx.AsyncClient(
            auth=httpx.BasicAuth(username, password),
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
            trust_env=False,
        ) as control:
            response = await control.get(f"{base_url}/api/config")
            assert response.status_code == 200
            document = response.json()
            text = json.dumps(document)
            assert "rakathon-azure" in text
            assert "deny" in text
            assert "tool.use" in text
            bad = await control.get(
                f"{base_url}/api/session", auth=httpx.BasicAuth(username, "wrong-password")
            )
            assert bad.status_code == 401
        client = OpenCodeClient(base_url, password, config.provider_id, config.model, timeout=60.0)
        await client.health()
        session_id = await client.create_session()
        assert session_id.startswith("ses_")
        answer = await client.generate(session_id, "say hi")
        assert answer == "hi"
        seen = dict(_FakeChatCompletions.seen)
        assert seen.get("path", "").endswith("/chat/completions")
        headers = seen.get("headers", {})
        assert headers.get("api-key") == _TEST_KEY
        assert "authorization" not in headers
        await client.interrupt(session_id)
        await client.delete(session_id)
    finally:
        if client is not None:
            await client.aclose()
        if process is not None:
            await process.close()
        server.shutdown()
        server.server_close()


def _run_wrapped_unshare(
    target: str, child_env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    command = (
        f"ip link set lo up && exec {sys.executable} -m pytest '{target}' -x -q -p no:cacheprovider"
    )
    return subprocess.run(
        ["unshare", "--user", "--map-root-user", "--net", "sh", "-c", command],
        check=False,
        capture_output=True,
        timeout=170,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env=child_env,
    )


async def test_azure_api_key_header_via_real_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _binary_available():
        pytest.skip("pinned opencode binary is not installed")
    if os.environ.get(_UNSHARE_GUARD) == "1":
        await _run_real_binary_flow(monkeypatch)
        return
    if _unshare_available():
        target = "tests/test_b5_azure_binary.py::test_azure_api_key_header_via_real_binary"
        opencode_dir = os.path.dirname(shutil.which("opencode") or "/usr/bin")
        child_env = {
            "PATH": f"{opencode_dir}:/usr/bin:/bin",
            "HOME": os.environ.get("HOME", "/tmp"),
            _UNSHARE_GUARD: "1",
            "UV_OFFLINE": "1",
        }
        proc = await asyncio.to_thread(_run_wrapped_unshare, target, child_env)
        assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
        assert "1 passed" in proc.stdout, proc.stdout[-2000:] + proc.stderr[-2000:]
        return
    await _run_real_binary_flow(monkeypatch)


async def test_child_env_stays_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.com:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.com:8080")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.example.com")
    monkeypatch.setenv("SOME_GLOBAL_CREDENTIAL", "leak-me-not")
    captured: dict[str, Any] = {}

    class _FakeProc:
        returncode = 0
        pid = 424242

        async def communicate(self) -> tuple[bytes, bytes]:
            return (b"opencode v2.0.31\n", b"")

        def kill(self) -> None:
            self.returncode = -9

        async def wait(self) -> int:
            return 0

    async def fake_spawn(*args: Any, **kwargs: Any) -> _FakeProc:
        captured["env"] = dict(kwargs.get("env", {}))
        return _FakeProc()

    async def fake_probe(binary: str, expected: str, timeout: float = 10.0) -> str:
        _ = (binary, expected, timeout)
        return "2.0.31"

    async def fake_ready(self: OpenCodeProcess) -> None:
        _ = self

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(proc_module, "probe_version", fake_probe)
    monkeypatch.setattr(OpenCodeProcess, "_wait_ready", fake_ready)
    proc = OpenCodeProcess(
        "opencode",
        "2.0.31",
        "rakathon-azure",
        "tiny",
        "https://apim-rakathon-q7146n.azure-api.net/openai/v1",
        startup_timeout=5.0,
        api_key=_TEST_KEY,
        provider_kind="azure",
    )
    try:
        await proc.start()
        env = captured["env"]
        assert env.get("RAKATHON_AI_API_KEY") == _TEST_KEY
        for leaked in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "SOME_GLOBAL_CREDENTIAL",
        ):
            assert leaked not in env
        assert env.get("OPENCODE_LOG_LEVEL") == "error"
    finally:
        await proc.close()
