from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import signal
import socket
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Self

import httpx

from rakathon_backend.b5.opencode.file_config import build_file_config_content
from rakathon_backend.b5.opencode.validation import (
    API_USERNAME,
    CONNECT_TIMEOUT,
    HEALTH_POLL_INTERVAL,
    PROCESS_KILL_TIMEOUT,
    VERSION_PROBE_TIMEOUT,
    build_config_content,
    parse_version_output,
)
from rakathon_backend.common.errors import TransportError

SCRATCH_BASE = "/tmp/opencode"
CHILD_HOST = "127.0.0.1"


def _child_env(scratch: Path, config_content: str, password: str, api_key: str) -> dict[str, str]:
    env: dict[str, str] = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": str(scratch),
        "XDG_CONFIG_HOME": str(scratch / "config"),
        "XDG_DATA_HOME": str(scratch / "data"),
        "XDG_STATE_HOME": str(scratch / "state"),
        "XDG_CACHE_HOME": str(scratch / "cache"),
        "TMPDIR": str(scratch / "tmp"),
        "OPENCODE_CONFIG_CONTENT": config_content,
        "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
        "OPENCODE_PURE": "1",
        "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
        "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
        "OPENCODE_DISABLE_EMBEDDED_WEB_UI": "1",
        "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "OPENCODE_DISABLE_MODELS_FETCH": "1",
        "OPENCODE_DISABLE_AUTOCOMPACT": "1",
        "OPENCODE_LOG_LEVEL": "error",
        "OPENCODE_DB": ":memory:",
        "OPENCODE_SERVER_PASSWORD": password,
    }
    if api_key:
        env["RAKATHON_AI_API_KEY"] = api_key
    return env


async def probe_version(binary: str, expected: str, timeout: float = VERSION_PROBE_TIMEOUT) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            binary,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            stdin=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, FileNotFoundError) as exc:
        raise TransportError(code="ai_binary", message="opencode binary is missing") from exc
    try:
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError as exc:
            raise TransportError(
                code="ai_binary", message="opencode version probe timed out"
            ) from exc
        if proc.returncode != 0:
            raise TransportError(code="ai_binary", message="opencode version probe failed")
        try:
            return parse_version_output(out.decode("utf-8", "replace"), expected)
        except ValueError as exc:
            raise TransportError(code="ai_version", message=str(exc)) from exc
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except (OSError, ProcessLookupError):
                pass
            await proc.wait()


def reserve_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((CHILD_HOST, 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


class OpenCodeProcess:
    def __init__(
        self,
        binary: str,
        expected_version: str,
        provider_id: str,
        model: str,
        provider_base_url: str,
        *,
        startup_timeout: float,
        api_key: str = "",
        provider_kind: str = "local",
        file_mode: bool = False,
    ) -> None:
        self._binary = binary
        self._expected = expected_version
        self._provider_id = provider_id
        self._model = model
        self._provider_base_url = provider_base_url
        self._provider_kind = provider_kind
        self._file_mode = file_mode
        self._startup_timeout = startup_timeout
        self._api_key = api_key
        self._proc: asyncio.subprocess.Process | None = None
        self._scratch: Path | None = None
        self._base_url = ""
        self._password = ""
        self._started = False
        self._closed = False

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def started(self) -> bool:
        return self._started and not self._closed

    async def start(self) -> str:
        if self._started:
            raise TransportError(code="ai_started", message="opencode process already started")
        await probe_version(self._binary, self._expected)
        if self._file_mode:
            config_content = build_file_config_content(
                self._provider_id,
                self._model,
                self._provider_base_url,
            )
        else:
            config_content = build_config_content(
                self._provider_id,
                self._model,
                self._provider_base_url,
                provider_kind=self._provider_kind,
            )
        password = secrets.token_urlsafe(48)
        base = Path(SCRATCH_BASE)
        base.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(base, 0o700)
        except OSError:
            pass
        scratch = Path(tempfile.mkdtemp(prefix="ai-", dir=str(base)))
        try:
            os.chmod(scratch, 0o700)
        except OSError:
            pass
        for sub in ("config", "data", "state", "cache", "tmp"):
            child = scratch / sub
            child.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(child, 0o700)
            except OSError:
                pass
        self._scratch = scratch
        self._password = password
        port = reserve_port()
        self._base_url = f"http://{CHILD_HOST}:{port}"
        env = _child_env(scratch, config_content, password, self._api_key)
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                "serve",
                f"--hostname={CHILD_HOST}",
                f"--port={port}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                stdin=asyncio.subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
        except (OSError, FileNotFoundError) as exc:
            await self._cleanup_scratch()
            raise TransportError(code="ai_spawn", message="opencode spawn failed") from exc
        self._proc = proc
        try:
            await self._wait_ready()
        except TransportError:
            await self.close()
            raise
        except Exception as exc:
            await self.close()
            raise TransportError(code="ai_ready", message="opencode readiness failed") from exc
        self._started = True
        return self._base_url

    def auth(self) -> tuple[str, str]:
        return (API_USERNAME, self._password)

    async def _wait_ready(self) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._startup_timeout
        timeout = httpx.Timeout(CONNECT_TIMEOUT, connect=CONNECT_TIMEOUT)
        async with httpx.AsyncClient(
            auth=httpx.BasicAuth(API_USERNAME, self._password),
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as http:
            while True:
                proc = self._proc
                if proc is not None and proc.returncode is not None:
                    raise TransportError(code="ai_exit", message="opencode child exited early")
                try:
                    response = await http.get(f"{self._base_url}/api/session")
                    if response.status_code == 200:
                        return
                except (httpx.HTTPError, OSError):
                    pass
                if loop.time() >= deadline:
                    raise TransportError(code="ai_ready", message="opencode readiness timed out")
                await asyncio.sleep(HEALTH_POLL_INTERVAL)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        proc = self._proc
        self._proc = None
        if proc is not None and proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
            try:
                await asyncio.wait_for(proc.wait(), PROCESS_KILL_TIMEOUT)
            except TimeoutError:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
                try:
                    await proc.wait()
                except (OSError, ProcessLookupError):
                    pass
        self._password = ""
        await self._cleanup_scratch()

    async def _cleanup_scratch(self) -> None:
        scratch = self._scratch
        self._scratch = None
        if scratch is not None:
            await asyncio.to_thread(shutil.rmtree, scratch, True)

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
