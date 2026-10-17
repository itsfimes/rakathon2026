from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
from contextlib import suppress
from pathlib import Path

from rakathon_backend.b5.direct import DirectAdapter, direct_config_from_env
from rakathon_backend.b5.direct_http import DirectHttpTransport
from rakathon_backend.b5.safety import configured_kill_file
from rakathon_backend.runtime.application import BackendApp, fresh_tokens
from rakathon_backend.runtime.iris_fhir import build_iris_fhir_app
from rakathon_backend.web.http import WebServer
from rakathon_backend.web.security import checked_origins, proxy_key
from rakathon_backend.web.service import WebService


async def close_app(app: BackendApp) -> None:
    try:
        await app.close()
    finally:
        close = getattr(app.store, "close", None)
        if callable(close):
            await asyncio.to_thread(close)


async def serve_app(
    app: BackendApp,
    bind: str,
    port: int,
    key: str,
    origins: frozenset[str],
    stop: asyncio.Event,
    assistant_enabled: bool = False,
) -> None:
    server: WebServer | None = None
    runner: asyncio.Task[None] | None = None
    try:
        await app.start()
        server = WebServer(
            bind,
            port,
            WebService.from_app(app, assistant_enabled),
            asyncio.get_running_loop(),
            key,
            origins,
        )
        runner = asyncio.create_task(asyncio.to_thread(server.serve_forever, 0.1))
        print(
            json.dumps(
                {
                    "serving": True,
                    "mode": app.mode,
                    "access": "single-user-development",
                    "port": server.server_address[1],
                }
            ),
            flush=True,
        )
        await stop.wait()
    finally:
        try:
            if server is not None:
                try:
                    if runner is not None:
                        await asyncio.to_thread(server.shutdown)
                        await runner
                finally:
                    await asyncio.to_thread(server.server_close)
        finally:
            await close_app(app)


async def cmd_web_serve(args: argparse.Namespace) -> int:
    app: BackendApp | None = None
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    installed: list[signal.Signals] = []
    adapter: DirectAdapter | None = None
    try:
        origins = checked_origins(args.frontend_origin)
        if args.bind != "127.0.0.1" or not 1 <= args.port <= 65535:
            raise ValueError("invalid listener")
        key = proxy_key(Path(args.proxy_key_file))
        enabled = os.environ.get("RAKATHON_WEB_ASSISTANT_ENABLE") == "1"
        if enabled:
            if os.environ.get("RAKATHON_AI_AUTH_SCHEME") not in (
                "api-key",
                "bearer",
                "subscription-key",
                "Ocp-Apim-Subscription-Key",
            ):
                raise ValueError("Web assistant requires an explicit authentication scheme")
            config = direct_config_from_env()
            if config.auth_scheme == "none":
                raise ValueError("Web assistant requires explicit provider authentication")
            if config.timeout_seconds > 60:
                raise ValueError("Web assistant provider timeout must not exceed 60 seconds")
            adapter = DirectAdapter(DirectHttpTransport(config))
        app = build_iris_fhir_app(
            Path(args.runtime_dir),
            fresh_tokens(),
            adapter=adapter,
            ai_mode="direct" if enabled else "mock",
            kill_file=configured_kill_file() if enabled else None,
        )
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
            installed.append(sig)
        owned_app, app = app, None
        await serve_app(owned_app, args.bind, args.port, key, origins, stop, enabled)
        return 0
    except (OSError, ValueError, RuntimeError):
        print(json.dumps({"error": "web_startup_or_runtime_failed"}), flush=True)
        return 1
    finally:
        if app is not None:
            with suppress(Exception):
                await close_app(app)
        if adapter is not None:
            with suppress(OSError, RuntimeError):
                await adapter.close()
        for sig in installed:
            loop.remove_signal_handler(sig)
