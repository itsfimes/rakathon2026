from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.ipc import UnixJsonClient
from rakathon_backend.common.rpc import new_envelope, socket_for
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.web.assistant import validate_request
from rakathon_backend.web.contracts import WebError
from rakathon_backend.web.projection import ID
from rakathon_backend.web.router import VerifiedIdentity
from rakathon_backend.web.service import WebService

WEB_SOURCE = "web:auth"
READ_TIMEOUT = 7.0
AI_TIMEOUT = 85.0
SESSION_PATH = "/api/v1/session"
WORKSPACE_PATH = "/api/v1/workspace"
CASES_PREFIX = "/api/v1/cases/"
ASSISTANT_PATH = "/api/v1/assistant"


def _error(status: int, code: str, message: str) -> tuple[int, dict[str, Any]]:
    return (status, {"version": 1, "error": {"code": code, "message": message}})


def _from_web_error(exc: WebError) -> tuple[int, dict[str, Any]]:
    return _error(int(exc.status), str(exc.code), str(exc.message))


class IdentityClient:
    def __init__(
        self, runtime_dir: Path | str, token: str, user_id: str, timeout: float = READ_TIMEOUT
    ) -> None:
        self._dir = Path(runtime_dir)
        self._token = token
        self._user_id = user_id
        self._timeout = float(timeout)

    async def call(self, envelope: Envelope, *, expect_source: str | None = None) -> Envelope:
        req = new_envelope(
            source=WEB_SOURCE,
            target="b4",
            action=envelope.action,
            data_kind=envelope.data_kind,
            payload=dict(envelope.payload),
            user_id=self._user_id,
            request_id=envelope.request_id,
            correlation_id=envelope.correlation_id,
        )
        client = UnixJsonClient(
            socket_for(self._dir, "b4"), token=self._token, source=WEB_SOURCE, timeout=self._timeout
        )
        return await client.call(req, expect_source=expect_source or "b4")

    async def ping(self, service: str) -> Any:
        client = UnixJsonClient(
            socket_for(self._dir, service),
            token=self._token,
            source=WEB_SOURCE,
            timeout=self._timeout,
        )
        return await client.ping(service)


async def human_may_ask(
    runtime_dir: Path | str, token: str, user_id: str, timeout: float = 5.0
) -> bool:
    uid = user_id.strip()
    if not uid:
        return False
    req = new_envelope(
        source=WEB_SOURCE,
        target="b6",
        action="authorize",
        data_kind=DataKind.METADATA,
        payload={"userId": uid, "action": "ai.ask"},
        user_id=uid,
    )
    client = UnixJsonClient(
        socket_for(Path(runtime_dir), "b6"), token=token, source=WEB_SOURCE, timeout=timeout
    )
    try:
        reply = await client.call(req, expect_source="b6")
    except (AuthError, ContractError, TransportError, OSError, TimeoutError, ValueError):
        return False
    except (KeyError, RuntimeError, AttributeError, TypeError):
        return False
    try:
        if reply.source != "b6" or reply.action != "authorize":
            return False
        if reply.data_kind != DataKind.METADATA:
            return False
        return reply.payload.get("allowed") is True
    except (AttributeError, ValueError, TypeError):
        return False


class AuthBridge:
    def __init__(
        self,
        runtime_dir: Path | str,
        web_token: str,
        *,
        assistant_enabled: bool = False,
        assistant_ready: Callable[[], bool] | None = None,
        uploads: UploadStore | None = None,
    ) -> None:
        if not isinstance(web_token, str) or not web_token:
            raise ValueError("web token must be nonempty")
        self._dir = Path(runtime_dir)
        self._token = web_token
        self._uploads = uploads
        self._assistant_enabled = bool(assistant_enabled)
        self._ready = assistant_ready if assistant_ready is not None else (lambda: False)
        self._ai_gate = threading.Semaphore(1)

    def protected(
        self, identity: VerifiedIdentity, method: str, path: str, body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        is_assistant_post = method == "POST" and path == ASSISTANT_PATH
        gate_held = False
        if is_assistant_post:
            try:
                validate_request(body)
            except WebError as exc:
                return _from_web_error(exc)
            if not self._ai_gate.acquire(blocking=False):
                return _error(429, "unavailable", "Assistant is busy")
            gate_held = True
        try:
            return asyncio.run(self._handle_async(identity, method, path, body))
        except WebError as exc:
            return _from_web_error(exc)
        except (ContractError, ValueError, KeyError, TypeError):
            return _error(400, "bad_request", "Request rejected")
        except AuthError:
            return _error(403, "forbidden", "Request forbidden")
        except (TransportError, OSError, TimeoutError, RuntimeError, AttributeError):
            return _error(503, "unavailable", "Backend unavailable")
        finally:
            if gate_held:
                self._ai_gate.release()

    async def _handle_async(
        self, identity: VerifiedIdentity, method: str, path: str, body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        if method == "GET" and path == SESSION_PATH:
            return await self._session(identity)
        if method == "GET" and path == WORKSPACE_PATH:
            return await self._workspace(identity)
        if path.startswith(CASES_PREFIX):
            if method != "GET":
                return _error(405, "method_not_allowed", "Only GET is supported")
            case_id = path[len(CASES_PREFIX) :]
            if ID.fullmatch(case_id) is None or "/" in case_id:
                return _error(400, "bad_request", "Invalid case identifier")
            return await self._case(identity, case_id)
        if path == ASSISTANT_PATH:
            if method != "POST":
                return _error(405, "method_not_allowed", "Only POST is supported")
            return await self._assistant(identity, body)
        if path in (SESSION_PATH, WORKSPACE_PATH) or path.startswith(CASES_PREFIX):
            return _error(405, "method_not_allowed", "Method not allowed")
        return _error(404, "not_found", "Endpoint not found")

    def _service_for(
        self, identity: VerifiedIdentity, *, with_assistant: bool, human_allowed: bool
    ) -> WebService:
        read_client = IdentityClient(self._dir, self._token, identity.user_id, READ_TIMEOUT)
        ai_client: IdentityClient | None = None
        if with_assistant and human_allowed and self._assistant_enabled and self._ready():
            ai_client = IdentityClient(self._dir, self._token, "web-assistant", AI_TIMEOUT)
        return WebService(
            read_client,
            ai_client,
            lambda: bool(self._assistant_enabled and self._ready() and ai_client is not None),
            uploads=self._uploads,
        )

    async def _session(self, identity: VerifiedIdentity) -> tuple[int, dict[str, Any]]:
        try:
            human = await human_may_ask(self._dir, self._token, identity.user_id)
        except (OSError, ValueError, RuntimeError):
            human = False
        svc = self._service_for(identity, with_assistant=True, human_allowed=human)
        try:
            return await svc.session()
        except WebError:
            raise
        except (ContractError, AuthError, TransportError, OSError, ValueError):
            raise WebError(503, "unavailable", "Backend unavailable")

    async def _workspace(self, identity: VerifiedIdentity) -> tuple[int, dict[str, Any]]:
        svc = self._service_for(identity, with_assistant=False, human_allowed=False)
        try:
            return await svc.workspace()
        except WebError:
            raise
        except (ContractError, AuthError, TransportError, OSError, ValueError):
            raise WebError(503, "unavailable", "Backend unavailable")

    async def _case(self, identity: VerifiedIdentity, case_id: str) -> tuple[int, dict[str, Any]]:
        try:
            human = await human_may_ask(self._dir, self._token, identity.user_id)
        except (OSError, ValueError, RuntimeError):
            human = False
        svc = self._service_for(identity, with_assistant=True, human_allowed=human)
        try:
            return await svc.case(case_id)
        except WebError:
            raise
        except (ContractError, AuthError, TransportError, OSError, ValueError):
            raise WebError(503, "unavailable", "Case unavailable")

    async def _assistant(
        self, identity: VerifiedIdentity, body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        validate_request(body)
        try:
            human = await human_may_ask(self._dir, self._token, identity.user_id)
        except (OSError, ValueError, RuntimeError):
            human = False
        if not human:
            raise WebError(403, "forbidden", "Assistant is not permitted")
        if not (self._assistant_enabled and self._ready()):
            raise WebError(503, "unavailable", "Assistant is not configured")
        svc = self._service_for(identity, with_assistant=True, human_allowed=True)
        try:
            return await svc.send_assistant(body)
        except WebError:
            raise
        except (ContractError, AuthError, TransportError, OSError, ValueError):
            raise WebError(503, "unavailable", "Assistant unavailable")
