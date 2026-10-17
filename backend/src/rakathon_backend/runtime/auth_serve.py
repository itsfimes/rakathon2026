from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import secrets
import signal
import sys
import threading
from pathlib import Path
from typing import Any

from rakathon_backend.b2.auth.iris_store import IrisAuthStore
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b2.iris.config import IrisSqlConfig
from rakathon_backend.b5.direct import DirectAdapter, direct_config_from_env
from rakathon_backend.b5.direct_http import DirectHttpTransport
from rakathon_backend.b5.gateway import AIAdapter
from rakathon_backend.b5.safety import configured_kill_file, kill_requested
from rakathon_backend.b7.client import B7SocketClient
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.common.errors import ContractError, TransportError
from rakathon_backend.runtime.auth_bundle import (
    WEB_SOURCE,
    build_auth_app,
    check_auth_dir,
    db_path_for,
    fresh_tokens_with_auth,
    load_auth_service,
    proxy_path_for,
)
from rakathon_backend.runtime.iris_fhir import IRIS_FHIR_MODE, build_iris_fhir_app
from rakathon_backend.runtime.screening_cmds import archive_store_from_env
from rakathon_backend.web.auth_bridge import AuthBridge
from rakathon_backend.web.config import WebConfig, load_proxy_key
from rakathon_backend.web.edge import build_login_callables
from rakathon_backend.web.router import AuthHTTPRouter
from rakathon_backend.web.server import build_server, check_bind_host, serve_forever


def _auth_store_for(name: str, auth_dir: Path) -> Any:
    if name == "demo":
        return SQLiteDemoAuthStore(db_path_for(auth_dir))
    if name == "iris":
        return IrisAuthStore(IrisSqlConfig.from_env())
    raise ContractError(code="not_configured", message="auth store unknown")


def _stop_http(server: Any, thread: threading.Thread) -> None:
    with contextlib.suppress(Exception):
        server.shutdown()
    thread.join(timeout=10.0)
    with contextlib.suppress(Exception):
        server.server_close()


async def cmd_auth_serve(args: argparse.Namespace) -> int:
    auth_store = str(getattr(args, "auth_store", "") or "")
    if auth_store not in ("demo", "iris"):
        print(json.dumps({"error": "auth-store is required: demo or iris"}))
        return 2
    auth_dir = Path(str(getattr(args, "auth_dir", "") or ""))
    if not str(auth_dir):
        print(json.dumps({"error": "auth-dir is required"}))
        return 2
    origin = str(getattr(args, "origin", "") or "")
    if not origin:
        print(json.dumps({"error": "origin is required"}))
        return 2
    allow_loopback = bool(getattr(args, "allow_loopback_http", False))
    try:
        web_config = WebConfig.build(origin, allow_loopback)
    except ContractError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        return 2
    try:
        check_auth_dir(auth_dir)
        proxy_key = load_proxy_key(proxy_path_for(auth_dir))
        store = _auth_store_for(auth_store, auth_dir)
        service, _ = load_auth_service(auth_dir, store, provider=LocalPasswordProvider())
    except ContractError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        return 1
    storage = str(getattr(args, "storage", "mock") or "mock")
    if storage not in ("mock", IRIS_FHIR_MODE):
        print(json.dumps({"error": "storage must be mock or iris-fhir"}))
        return 2
    screening: Any | None = None
    with contextlib.suppress(ContractError, TransportError, OSError, ValueError):
        screening = archive_store_from_env(None)
    runtime_dir = Path(str(getattr(args, "runtime_dir", "") or ""))
    if not str(runtime_dir):
        print(json.dumps({"error": "runtime-dir is required for auth-serve"}))
        return 2
    assistant_flag = bool(getattr(args, "assistant", False))
    env_assistant = os.environ.get("RAKATHON_WEB_ASSISTANT_ENABLE") == "1"
    requested = assistant_flag or env_assistant
    adapter: AIAdapter | None = None
    ai_mode = "mock"
    kill_file: Path | None = None
    if requested:
        if os.environ.get("RAKATHON_AI_AUTH_SCHEME") not in (
            "api-key",
            "bearer",
            "subscription-key",
            "Ocp-Apim-Subscription-Key",
        ):
            print(json.dumps({"error": "assistant_requires_explicit_auth_scheme"}))
            return 2
        try:
            direct_config = direct_config_from_env()
        except (ContractError, TransportError, ValueError) as exc:
            print(json.dumps({"error": "ai_not_configured", "message": str(exc)}))
            return 2
        if direct_config.auth_scheme == "none":
            print(json.dumps({"error": "assistant_requires_explicit_auth_scheme"}))
            return 2
        if direct_config.timeout_seconds > 60:
            print(json.dumps({"error": "assistant_timeout_must_not_exceed_60"}))
            return 2
        try:
            adapter = DirectAdapter(DirectHttpTransport(direct_config))
        except (ContractError, TransportError, OSError, ValueError) as exc:
            print(json.dumps({"error": "ai_not_configured", "message": str(exc)}))
            return 2
        ai_mode = "direct"
        kill_file = configured_kill_file()
    tokens = fresh_tokens_with_auth()
    try:
        if storage == IRIS_FHIR_MODE:
            base = build_iris_fhir_app(
                runtime_dir,
                dict(tokens),
                adapter=adapter,
                ai_mode=ai_mode,
                kill_file=kill_file,
                screening=screening,
            )
            app = build_auth_app(
                runtime_dir,
                tokens,
                service,
                store=base.store,
                mode=base.mode,
                screening=screening,
                ai_adapter=adapter,
                ai_mode=ai_mode,
                kill_file=kill_file,
            )
            app.screening = screening
        else:
            app = build_auth_app(
                runtime_dir,
                tokens,
                service,
                mode="mock",
                screening=screening,
                ai_adapter=adapter,
                ai_mode=ai_mode,
                kill_file=kill_file,
            )
    except (ContractError, TransportError, OSError, ValueError) as exc:
        if adapter is not None:
            with contextlib.suppress(OSError, RuntimeError):
                await adapter.close()
        print(json.dumps({"error": "serve_startup_failed", "message": str(exc)}))
        return 1
    try:
        await app.start()
    except (ContractError, TransportError, OSError, ValueError, RuntimeError) as exc:
        if adapter is not None:
            with contextlib.suppress(OSError, RuntimeError):
                await adapter.close()
        print(json.dumps({"error": "serve_startup_failed", "message": str(exc)}))
        return 1
    login, resolve, csrf_for, logout = build_login_callables(
        B7SocketClient(runtime_dir, tokens[WEB_SOURCE])
    )
    router = AuthHTTPRouter(web_config, proxy_key, login, resolve, csrf_for, logout)
    binding_root = secrets.token_bytes(32)

    def _assistant_ready() -> bool:
        try:
            gateway = app.gateway
            if gateway is None or gateway.mode != "direct":
                return False
            if gateway.switch.tripped:
                return False
            return not kill_requested(configured_kill_file())
        except (OSError, ValueError, RuntimeError, AttributeError):
            return False

    bridge = AuthBridge(
        runtime_dir,
        tokens[WEB_SOURCE],
        binding_root,
        assistant_enabled=(requested and ai_mode == "direct"),
        assistant_ready=_assistant_ready,
    )
    router.set_protected(bridge.protected)
    try:
        bind = check_bind_host(str(getattr(args, "bind", "127.0.0.1") or "127.0.0.1"))
    except ValueError:
        await app.close()
        if adapter is not None:
            with contextlib.suppress(OSError, RuntimeError):
                await adapter.close()
        print(json.dumps({"error": "bind must be loopback"}))
        return 2
    raw_port = getattr(args, "port", 8765)
    try:
        port = int(raw_port if raw_port is not None else 8765)
    except (TypeError, ValueError):
        print(json.dumps({"error": "port invalid"}))
        return 2
    try:
        server = build_server(bind, port, router)
    except ValueError:
        await app.close()
        if adapter is not None:
            with contextlib.suppress(OSError, RuntimeError):
                await adapter.close()
        print(json.dumps({"error": "bind must be loopback"}))
        return 2
    stop = asyncio.Event()

    def _handler(*args: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handler)
        except (NotImplementedError, RuntimeError):
            pass
    thread = threading.Thread(target=serve_forever, args=(server,), daemon=True)
    thread.start()
    print(
        json.dumps(
            {
                "serving": True,
                "authStore": auth_store,
                "storage": storage,
                "origin": web_config.origin,
                "bind": bind,
                "port": int(server.server_address[1]),
                "cookie": web_config.cookie_name,
            }
        )
    )
    sys.stdout.flush()
    try:
        await stop.wait()
    finally:
        await asyncio.to_thread(_stop_http, server, thread)
        await app.close()
        if adapter is not None:
            with contextlib.suppress(OSError, RuntimeError):
                await adapter.close()
    return 0
