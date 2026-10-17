from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import signal
import sys
from pathlib import Path
from typing import Any

from rakathon_backend.b5.direct import DirectAdapter, direct_config_from_env
from rakathon_backend.b5.direct_http import DirectHttpTransport
from rakathon_backend.b5.gateway import AIAdapter
from rakathon_backend.b5.safety import configured_kill_file
from rakathon_backend.bridge.client import EncryptedBridgeStorage
from rakathon_backend.bridge.crypto import generate_key_file
from rakathon_backend.common.ai_limits import AI_EDGE_TIMEOUT
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.ipc import UnixJsonClient
from rakathon_backend.common.kinds import request_kind
from rakathon_backend.common.rpc import make_client, new_envelope, socket_for
from rakathon_backend.runtime import bridge_cmds as _bridge_cmds
from rakathon_backend.runtime.application import BackendApp, fresh_tokens
from rakathon_backend.runtime.demo import run_demo
from rakathon_backend.runtime.iris_fhir import IRIS_FHIR_MODE, build_iris_fhir_app
from rakathon_backend.runtime.paths import short_runtime
from rakathon_backend.runtime.screening_cmds import archive_store_from_env
from rakathon_backend.runtime.secret_config import remove_client_config, write_client_config

__all__ = ["short_runtime"]


async def cmd_demo(runtime_dir: Path) -> int:
    app = BackendApp(runtime_dir, fresh_tokens())
    await app.start()
    try:
        result = await run_demo(app)
    finally:
        await app.close()
    print(json.dumps(result, indent=2))
    return 0


def bridge_store_from_env() -> EncryptedBridgeStorage:
    return _bridge_cmds.bridge_store_from_env()


async def cmd_serve(
    runtime_dir: Path,
    storage: str,
    ai: str,
    watchdog_interval: float,
    screening_source: str | None = None,
) -> int:
    if watchdog_interval < 0.1:
        print(json.dumps({"error": "watchdog interval must be >= 0.1"}))
        return 2
    adapter: AIAdapter | None = None
    ai_mode = "mock"
    kill_file: Path | None = None
    if ai == "direct":
        try:
            adapter = DirectAdapter(DirectHttpTransport(direct_config_from_env()))
        except (ContractError, TransportError, ValueError):
            print(json.dumps({"error": "ai_not_configured"}))
            return 2
        ai_mode = "direct"
        kill_file = configured_kill_file()
    bridge_store: EncryptedBridgeStorage | None = None
    screening: Any | None = None
    try:
        screening = archive_store_from_env(screening_source)
    except (ContractError, TransportError, OSError, ValueError):
        if adapter is not None:
            await adapter.close()
        return 2
    if storage == "bridge":
        try:
            bridge_store = bridge_store_from_env()
        except (ContractError, TransportError, OSError, ValueError) as exc:
            print(json.dumps({"error": "bridge_not_configured", "message": str(exc)}))
            if adapter is not None:
                await adapter.close()
            return 2
        app = BackendApp(
            runtime_dir,
            fresh_tokens(),
            store=bridge_store,
            mode="bridge",
            ai_adapter=adapter,
            ai_mode=ai_mode,
            kill_file=kill_file,
            watchdog_interval=watchdog_interval,
            screening=screening,
        )
        serving_mode = "bridge"
    elif storage == IRIS_FHIR_MODE:
        try:
            app = build_iris_fhir_app(
                runtime_dir,
                fresh_tokens(),
                adapter=adapter,
                ai_mode=ai_mode,
                kill_file=kill_file,
                screening=screening,
            )
        except (ContractError, TransportError, OSError, ValueError) as exc:
            print(json.dumps({"error": "iris_not_configured", "message": str(exc)}))
            if adapter is not None:
                await adapter.close()
            return 2
        serving_mode = IRIS_FHIR_MODE
    else:
        app = BackendApp(
            runtime_dir,
            fresh_tokens(),
            ai_adapter=adapter,
            ai_mode=ai_mode,
            kill_file=kill_file,
            watchdog_interval=watchdog_interval,
            screening=screening,
        )
        serving_mode = "mock"
    try:
        await app.start()
    except (ContractError, TransportError, OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"error": "serve_startup_failed", "message": str(exc)}))
        if adapter is not None:
            await adapter.close()
        return 1
    write_client_config(runtime_dir, app.tokens, ai_mode, serving_mode)
    stop = asyncio.Event()

    def _handler(*args: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handler)
        except (NotImplementedError, RuntimeError):
            pass
    print(
        json.dumps(
            {
                "serving": True,
                "runtimeDir": str(runtime_dir),
                "mode": serving_mode,
                "aiMode": ai_mode,
                "screening": "archive" if screening is not None else "unconfigured",
            }
        )
    )
    sys.stdout.flush()
    try:
        await stop.wait()
    finally:
        await app.close()
        if bridge_store is not None:
            with contextlib.suppress(Exception):
                bridge_store.close()
        if serving_mode == IRIS_FHIR_MODE:
            with contextlib.suppress(Exception):
                close_fn = getattr(app.store, "close", None)
                if callable(close_fn):
                    close_fn()
        remove_client_config(runtime_dir)
    return 0


async def cmd_health(runtime_dir: Path) -> int:
    config_path = runtime_dir / "demo-client.json"
    tokens: dict[str, str] = {}
    if config_path.is_symlink():
        print(json.dumps({"status": "DOWN", "healthScope": "authenticated-ipc-liveness"}))
        return 1
    if config_path.exists():
        try:
            body = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(json.dumps({"status": "DOWN", "healthScope": "authenticated-ipc-liveness"}))
            return 1
        raw_tokens = body.get("tokens", {})
        if isinstance(raw_tokens, dict):
            tokens = {str(k): str(v) for k, v in raw_tokens.items()}
    if not tokens:
        print(
            json.dumps(
                {
                    "status": "DOWN",
                    "healthScope": "authenticated-ipc-liveness",
                    "deps": "not_checked",
                    "reason": "no client config; refusing to invent health",
                }
            )
        )
        return 1
    health = await health_via_config(runtime_dir, tokens)
    print(
        json.dumps(
            {"healthScope": "authenticated-ipc-liveness", "deps": "not_checked", **health},
            indent=2,
        )
    )
    return 0


async def health_via_config(runtime_dir: Path, tokens: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    probes = {
        "b6": "b4",
        "b2": "b4",
        "b5": "b1",
        "b1": "b4",
        "b4": "frontend:admin",
        "b3": "b3",
    }
    for service, source in probes.items():
        token = tokens.get(source, "")
        if not token:
            out[service] = "DOWN"
            continue
        client = UnixJsonClient(socket_for(runtime_dir, service), token=token, source=source)
        out[service] = (await client.ping(service)).value
    return out


def client_timeout_for(action: str) -> float:
    if action in ("ai.complete", "ingest"):
        return AI_EDGE_TIMEOUT
    return 5.0


async def cmd_client(args: argparse.Namespace) -> int:
    runtime_dir = Path(args.runtime_dir)
    config_path = runtime_dir / "demo-client.json"
    if not config_path.exists():
        print(json.dumps({"error": "missing demo-client.json"}))
        return 2
    body = json.loads(config_path.read_text(encoding="utf-8"))
    tokens = body.get("tokens", {})
    user = str(args.user)
    source = f"frontend:{user}"
    token = tokens.get(source, "")
    if not token:
        print(json.dumps({"error": "unknown user"}))
        return 2
    payload: dict[str, Any] = json.loads(args.payload_json or "{}")
    if not isinstance(payload, dict):
        print(json.dumps({"error": "payload must be an object"}))
        return 2
    client = make_client(
        runtime_dir,
        target="b4",
        source=source,
        token=str(token),
        timeout=client_timeout_for(str(args.action)),
    )
    request = new_envelope(
        source=source,
        target="b4",
        action=str(args.action),
        data_kind=request_kind(str(args.action)),
        payload=payload,
        user_id=user,
    )
    try:
        reply = await client.call(request, expect_source="b4")
    except (AuthError, ContractError, TransportError, OSError, TimeoutError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}))
        return 1
    mode = body.get("mode", "mock")
    if isinstance(reply.payload, dict) and isinstance(reply.payload.get("mode"), str):
        mode = reply.payload["mode"]
    print(json.dumps({"action": reply.action, "payload": reply.payload, "mode": mode}))
    return 0


def cmd_keygen(path: str, key_id: str | None) -> int:
    target = generate_key_file(Path(path))
    raw = target.read_bytes().strip()
    derived = hashlib.sha256(raw).hexdigest()[:16]
    resolved = key_id.strip() if key_id and key_id.strip() else derived
    print(json.dumps({"path": str(target), "keyId": resolved}))
    return 0


def cmd_bridge_serve(bind: str, port: int, mock_storage: bool) -> int:
    return _bridge_cmds.cmd_bridge_serve(bind, port, mock_storage)


def cmd_init_db() -> int:
    return _bridge_cmds.cmd_init_db()
