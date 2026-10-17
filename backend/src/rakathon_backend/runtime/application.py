from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from contextlib import AsyncExitStack, suppress
from pathlib import Path
from typing import Any

from rakathon_backend.b1.service import B1Service
from rakathon_backend.b1.service import make_handler as b1_handler
from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.b2.ports import Storage
from rakathon_backend.b2.screening.ports import ScreeningPort
from rakathon_backend.b2.service import B2Service
from rakathon_backend.b2.service import make_handler as b2_handler
from rakathon_backend.b3.service import B3Service
from rakathon_backend.b3.service import make_handler as b3_handler
from rakathon_backend.b4.router import B4Router
from rakathon_backend.b4.router import make_handler as b4_handler
from rakathon_backend.b5.gateway import AIAdapter, B5Gateway, KillSwitch, MockAdapter
from rakathon_backend.b5.gateway import make_handler as b5_handler
from rakathon_backend.b5.safety import check_ai_kill, kill_requested
from rakathon_backend.b6.permissions import load_matrix, make_authorize_handler, privileged_users
from rakathon_backend.b7.handler import make_handler as b7_handler
from rakathon_backend.common.ai_limits import (
    AI_EDGE_TIMEOUT,
    AI_FRONTEND_TIMEOUT,
    AI_GATEWAY_TIMEOUT,
    AI_IPC_TIMEOUT,
)
from rakathon_backend.common.blob_store import BlobStore
from rakathon_backend.common.contracts import DataKind
from rakathon_backend.common.ipc import UnixJsonClient, UnixJsonServer
from rakathon_backend.common.review_limits import (
    B2_REVIEW_ACTION_TIMEOUTS,
    B2_REVIEW_CLIENT_TIMEOUT,
    B4_REVIEW_ACTION_TIMEOUTS,
    B4_REVIEW_PENDING_TIMEOUT,
    REVIEW_ACTION,
)
from rakathon_backend.common.rpc import check_auth, make_client, new_envelope, socket_for
from rakathon_backend.runtime import app_health as _app_health
from rakathon_backend.runtime.fixtures import complete_fixture
from rakathon_backend.runtime.tokens import (
    AI_MODES,
    FRONTEND_USERS,
    KILL_POLL_SECONDS,
    MAX_WATCHDOG_INTERVAL,
    MIN_WATCHDOG_INTERVAL,
    SERVICES,
    _closer,
    fresh_tokens,
)

__all__ = ["BackendApp", "fresh_tokens"]


class BackendApp:
    def __init__(
        self,
        runtime_dir: Path,
        tokens: dict[str, str],
        store: Storage | None = None,
        mode: str = "mock",
        ai_adapter: AIAdapter | None = None,
        ai_mode: str = "mock",
        kill_switch: KillSwitch | None = None,
        kill_file: Path | str | None = None,
        watchdog_interval: float | None = None,
        screening: ScreeningPort | None = None,
        auth: Any | None = None,
    ) -> None:
        if ai_mode not in AI_MODES:
            raise ValueError("ai_mode must be mock, opencode or direct")
        if ai_mode != "mock" and ai_adapter is None:
            raise ValueError("opencode ai_mode requires an explicit adapter")
        if watchdog_interval is not None and not (
            MIN_WATCHDOG_INTERVAL <= watchdog_interval <= MAX_WATCHDOG_INTERVAL
        ):
            raise ValueError("watchdog interval out of bounds")
        self.runtime_dir = runtime_dir
        self.tokens = dict(tokens)
        self.blob = BlobStore()
        self.store: Storage = store if store is not None else MemoryStorage()
        self.screening = screening
        self.mode = mode
        self.ai_mode = ai_mode
        self._ai_adapter: AIAdapter = ai_adapter if ai_adapter is not None else MockAdapter()
        if kill_switch is not None:
            self._switch = kill_switch
        elif ai_mode != "mock":
            self._switch = KillSwitch(allow_remote=True)
        else:
            self._switch = KillSwitch()
        self._kill_file = Path(kill_file) if kill_file else None
        self._watchdog_interval = watchdog_interval
        self._auth = auth
        self._stack = AsyncExitStack()
        self._servers: dict[str, UnixJsonServer] = {}
        self._b3: B3Service | None = None
        self._b4: B4Router | None = None
        self._b5: B5Gateway | None = None
        self._kill_task: asyncio.Task[None] | None = None

    def registry(self) -> dict[str, str]:
        return {token: service for service, token in self.tokens.items()}

    def _token(self, service: str) -> str:
        return self.tokens[service]

    def internal_client(self, source: str, target: str) -> UnixJsonClient:
        return make_client(
            self.runtime_dir, target=target, source=source, token=self._token(source)
        )

    def frontend_client(self, user: str) -> UnixJsonClient:
        source = f"frontend:{user}"
        timeout = 85.0 if user == "web-assistant" and self.ai_mode == "direct" else 7.0
        return make_client(
            self.runtime_dir, target="b4", source=source, token=self._token(source), timeout=timeout
        )

    async def start(self) -> None:
        if self.ai_mode != "mock":
            check_ai_kill(self._kill_file)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.runtime_dir, 0o700)
        except OSError:
            pass
        ai_backed = self.ai_mode != "mock"
        ipc_timeout = AI_IPC_TIMEOUT if ai_backed else 5.0
        edge_timeout = AI_EDGE_TIMEOUT if ai_backed else 7.0
        registry = self.registry()
        policy = load_matrix()
        auth = self._auth
        if auth is not None:
            allowed: frozenset[str] = frozenset({"b4", "b3", "b2", "b1", "b5", "web:auth"})
        else:
            allowed = frozenset({"b4", "b3", "b2", "b1", "b5"})
        b6_handler = make_authorize_handler(
            policy,
            service_name="b6",
            allowed_sources=allowed,
            role_resolver=auth.role_resolver if auth is not None else None,
        )
        await self._add("b6", registry, b6_handler)
        if auth is not None:
            await self._add("b7", registry, b7_handler(auth.service))

        def make_b6check(source: str) -> Any:
            async def check(*, user_id: str, action: str, correlation_id: str) -> bool:
                inner = make_client(
                    self.runtime_dir, target="b6", source=source, token=self._token(source)
                )
                return await check_auth(
                    inner, user_id=user_id, action=action, correlation_id=correlation_id
                )

            return check

        b6_b2 = make_b6check("b2")
        b6_b5 = make_b6check("b5")
        b6_b1 = make_b6check("b1")
        b6_b4 = make_b6check("b4")
        b6_b3 = make_b6check("b3")
        b2 = B2Service(
            self.store,
            b6_b2,
            mode=self.mode,
            privileged_users=privileged_users(policy),
            screening=self.screening,
            is_privileged=auth.is_privileged if auth is not None else None,
        )
        await self._add(
            "b2", registry, b2_handler(b2), timeout=7.0, action_timeouts=B2_REVIEW_ACTION_TIMEOUTS
        )
        gateway_timeout = AI_GATEWAY_TIMEOUT if ai_backed else 60.0
        gateway = B5Gateway(
            self.blob,
            self._ai_adapter,
            b6_b5,
            self._switch,
            self.ai_mode,
            gateway_timeout,
            kill_file=self._kill_file,
        )
        self._b5 = gateway
        await self._add("b5", registry, b5_handler(gateway), timeout=ipc_timeout)

        def ai_client(source: str, target: str) -> Any:
            return make_client(
                self.runtime_dir,
                target=target,
                source=source,
                token=self._token(source),
                timeout=ipc_timeout,
            )

        async def via_b5(
            *, bytes_ref: str, purpose: str, user_id: str, correlation_id: str
        ) -> dict[str, Any]:
            client = ai_client("b1", "b5")
            req = new_envelope(
                source="b1",
                target="b5",
                action="ai.translate",
                data_kind=DataKind.PROPRIETARY,
                payload={"bytesRef": bytes_ref, "purpose": purpose},
                user_id=user_id,
                correlation_id=correlation_id,
            )
            reply = await client.call(req, expect_source="b5")
            return dict(reply.payload)

        b1 = B1Service(self.blob, via_b5, b6_b1)
        await self._add("b1", registry, b1_handler(b1), timeout=ipc_timeout)

        async def call_b1(request: Any) -> Any:
            client = ai_client("b4", "b1")
            return await client.call(request, expect_source="b1")

        async def call_b2(request: Any) -> Any:
            action = getattr(request, "action", "")
            timeout = B2_REVIEW_CLIENT_TIMEOUT if action == REVIEW_ACTION else 7.0
            client = make_client(
                self.runtime_dir, target="b2", source="b4", token=self._token("b4"), timeout=timeout
            )
            return await client.call(request, expect_source="b2")

        async def call_b5(request: Any) -> Any:
            client = ai_client("b4", "b5")
            return await client.call(request, expect_source="b5")

        source_users = {f"frontend:{u}": u for u in FRONTEND_USERS}
        router = B4Router(
            b6_b4,
            call_b1,
            call_b2,
            call_b5,
            source_users,
            ai_pending_timeout=AI_FRONTEND_TIMEOUT,
            review_pending_timeout=B4_REVIEW_PENDING_TIMEOUT,
            privileged_users=privileged_users(policy),
            web_sources=auth.web_sources if auth is not None else None,
            is_privileged=auth.is_privileged if auth is not None else None,
        )
        self._b4 = router
        await self._add(
            "b4",
            registry,
            b4_handler(router),
            timeout=edge_timeout,
            action_timeouts=B4_REVIEW_ACTION_TIMEOUTS,
        )

        async def fetch_tasks(correlation_id: str) -> list[dict[str, Any]]:
            client = make_client(
                self.runtime_dir, target="b2", source="b3", token=self._token("b3")
            )
            req = new_envelope(
                source="b3",
                target="b2",
                action="tasks.read",
                data_kind=DataKind.PROPRIETARY,
                payload={},
                user_id="watchdog",
                correlation_id=correlation_id,
            )
            reply = await client.call(req, expect_source="b2")
            items = reply.payload.get("tasks", [])
            return [t for t in items if isinstance(t, dict)]

        async def deliver(reminders: list[dict[str, Any]], correlation_id: str) -> None:
            client = make_client(
                self.runtime_dir, target="b4", source="b3", token=self._token("b3")
            )
            req = new_envelope(
                source="b3",
                target="b4",
                action="reminders.deliver",
                data_kind=DataKind.PROPRIETARY,
                payload={"reminders": reminders},
                user_id="watchdog",
                correlation_id=correlation_id,
            )
            await client.call(req, expect_source="b4")

        b3 = B3Service(fetch_tasks, deliver, b6_b3)
        self._b3 = b3
        await self._add("b3", registry, b3_handler(b3))
        try:
            if self._watchdog_interval is not None:
                await b3.start_loop(self._watchdog_interval)
            if self._kill_file is not None or self.ai_mode != "mock":
                self._kill_task = asyncio.create_task(self._kill_watch())
        except Exception:
            await self.close()
            raise

    async def _add(
        self,
        name: str,
        registry: dict[str, str],
        handler: Any,
        timeout: float = 5.0,
        action_timeouts: Mapping[str, float] | None = None,
    ) -> None:
        server = UnixJsonServer(
            socket_for(self.runtime_dir, name),
            service_name=name,
            token_registry=registry,
            handler=handler,
            timeout=timeout,
            action_timeouts=action_timeouts,
        )
        try:
            await server.start()
        except Exception:
            await self.close()
            raise
        self._servers[name] = server
        await self._stack.enter_async_context(_closer(server))

    async def _kill_watch(self) -> None:
        while not kill_requested(self._kill_file):
            await asyncio.sleep(KILL_POLL_SECONDS)
        gateway = self._b5
        if gateway is not None:
            with suppress(Exception):
                await gateway.trip()

    async def close(self) -> None:
        task = self._kill_task
        self._kill_task = None
        if task is not None:
            task.cancel()
            with suppress(Exception, asyncio.CancelledError):
                await task
        if self._b3 is not None:
            with suppress(Exception):
                await self._b3.stop_loop()
        if self._b5 is not None:
            with suppress(Exception):
                await self._b5.trip()
        await self._stack.aclose()
        self._servers.clear()

    async def health_all(self) -> dict[str, str]:
        return await _app_health.health_all(self, SERVICES)

    def seed_complete_blob(self) -> str:
        raw = json.dumps(complete_fixture()).encode()
        return self.blob.put(raw, "application/json")

    @property
    def b3service(self) -> B3Service | None:
        return self._b3

    @property
    def b4router(self) -> B4Router | None:
        return self._b4

    @property
    def gateway(self) -> B5Gateway | None:
        return self._b5

    @property
    def kill_switch(self) -> KillSwitch:
        return self._switch
