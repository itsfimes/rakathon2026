from __future__ import annotations

import asyncio
import contextlib
import stat
from pathlib import Path

from rakathon_backend.b5.opencode.client import OpenCodeClient
from rakathon_backend.b5.opencode.process import OpenCodeProcess
from rakathon_backend.b5.opencode.validation import AZURE_BASE_URL
from rakathon_backend.common.errors import TransportError

DEFAULT_PROVIDER_ID = "rakathon-azure"
DEFAULT_MODEL = "gpt-6-luna-dz-eu"
DEFAULT_BASE_URL = AZURE_BASE_URL
STARTUP_TIMEOUT = 30.0
INFERENCE_TIMEOUT = 180.0
TOTAL_TIMEOUT = 240.0


class AgentError(OSError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def read_secret_file(raw_path: str) -> str:
    path = Path(raw_path)
    if path.is_symlink():
        raise AgentError("secret_symlink", "secret file is a symlink")
    try:
        st = path.stat()
    except OSError as exc:
        raise AgentError("secret_unreadable", "secret file cannot be read") from exc
    if not stat.S_ISREG(st.st_mode):
        raise AgentError("secret_not_file", "secret file is not a regular file")
    if st.st_mode & 0o077:
        raise AgentError("secret_permissions", "secret file must be owner-only 0600")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AgentError("secret_unreadable", "secret file cannot be read") from exc
    key = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("RAKATHON_AI_API_KEY="):
            key = stripped.split("=", 1)[1].strip().strip("\"'")
            break
    if not key:
        key = text.strip()
    if not key:
        raise AgentError("secret_empty", "secret file carries no key")
    return key


async def _generate_once(
    prompt: str,
    *,
    provider_id: str,
    model: str,
    base_url: str,
    api_key: str,
    startup_timeout: float,
    inference_timeout: float,
) -> str:
    process = OpenCodeProcess(
        "opencode",
        "2.0.31",
        provider_id,
        model,
        base_url,
        startup_timeout=startup_timeout,
        api_key=api_key,
        provider_kind="azure",
    )
    base = await process.start()
    username, password = process.auth()
    _ = username
    client = OpenCodeClient(base, password, provider_id, model, timeout=inference_timeout)
    session_id = ""
    try:
        try:
            session_id = await client.create_session()
        except TransportError as exc:
            raise AgentError("session_failed", exc.message) from exc
        try:
            return await client.generate(session_id, prompt)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await asyncio.shield(client.interrupt(session_id))
            raise
        except TransportError as exc:
            raise AgentError("inference_failed", exc.message) from exc
    finally:
        if session_id:
            with contextlib.suppress(Exception):
                await client.delete(session_id)
        with contextlib.suppress(Exception):
            await client.aclose()
        with contextlib.suppress(Exception):
            await process.close()


def run_model_once(
    prompt: str,
    *,
    provider_id: str = DEFAULT_PROVIDER_ID,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    api_key: str,
    startup_timeout: float = STARTUP_TIMEOUT,
    inference_timeout: float = INFERENCE_TIMEOUT,
    total_timeout: float = TOTAL_TIMEOUT,
) -> str:
    if not api_key:
        raise AgentError("secret_missing", "api key is required for the azure call")
    if base_url.strip().rstrip("/") != AZURE_BASE_URL:
        raise AgentError("untrusted_endpoint", "only the trusted azure endpoint is allowed")

    async def _main() -> str:
        try:
            return await asyncio.wait_for(
                _generate_once(
                    prompt,
                    provider_id=provider_id,
                    model=model,
                    base_url=AZURE_BASE_URL,
                    api_key=api_key,
                    startup_timeout=startup_timeout,
                    inference_timeout=inference_timeout,
                ),
                total_timeout,
            )
        except TimeoutError as exc:
            raise AgentError("agent_timeout", "converter agent exceeded its budget") from exc

    try:
        return asyncio.run(_main())
    except AgentError:
        raise
    except (OSError, RuntimeError) as exc:
        raise AgentError("agent_failed", "converter agent failed") from exc
