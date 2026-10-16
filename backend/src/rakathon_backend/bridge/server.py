from __future__ import annotations

import contextlib
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from rakathon_backend.b2.validation import validate_public_task_create
from rakathon_backend.bridge.audit import AuditSink, file_audit_sink
from rakathon_backend.bridge.crypto import BridgeCrypto, load_key
from rakathon_backend.bridge.protocol import check_arguments, check_operation, check_outer
from rakathon_backend.bridge.replay import ReplayCache
from rakathon_backend.bridge.screening import SCREENING_OPERATIONS, dispatch_screening
from rakathon_backend.common.errors import AuthError, ContractError, TransportError

MAX_BODY_BYTES = 1024 * 1024
RPC_PATH = "/rpc"
MAX_WORKERS = 16
_USER_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

_WRITE_AUDIT_OPS = frozenset({"fhir.write", "tasks.write", "tasks.ack", "screening.import"})


def _strict_user(value: Any) -> str:
    if not isinstance(value, str) or _USER_RE.fullmatch(value.strip()) is None:
        raise ContractError(code="bad_payload", message="user id invalid")
    return value.strip()


class BridgeDispatcher:
    def __init__(
        self,
        crypto: BridgeCrypto,
        store: Any,
        replay: ReplayCache,
        mode: str = "mock",
        allowed_users: frozenset[str] | None = None,
        audit: AuditSink | None = None,
        screening: Any | None = None,
    ) -> None:
        self._crypto = crypto
        self._store = store
        self._replay = replay
        self._mode = mode
        self._allowed = frozenset(allowed_users) if allowed_users else None
        self._audit = audit
        self._screening = screening if screening is not None else getattr(store, "screening", None)

    def _note(self, request_id: str, operation: str, actor: str, status: str) -> None:
        sink = self._audit
        if sink is None:
            return
        record = {
            "timestamp": time.time(),
            "requestId": request_id,
            "operation": operation,
            "assertedActor": actor,
            "status": status,
        }
        with contextlib.suppress(Exception):
            sink(record)

    def handle_outer(self, raw: Any) -> tuple[int, dict[str, Any], bool]:
        try:
            key_id, token = check_outer(raw)
        except ContractError:
            return (400, {"error": {"code": "bad_envelope", "message": "request refused"}}, False)
        if key_id != self._crypto.key_id:
            return (401, {"error": {"code": "auth_failed", "message": "request refused"}}, False)
        try:
            inner = self._crypto.decrypt_request(token)
        except ContractError:
            return (401, {"error": {"code": "auth_failed", "message": "request refused"}}, False)
        operation = str(inner.get("operation", ""))
        request_id = str(inner.get("requestId", ""))
        try:
            check_operation(operation)
            self._replay.check_and_store(key_id, request_id)
            args = check_arguments(operation, inner.get("arguments"))
            result = self._dispatch(operation, args)
        except ContractError as exc:
            if operation in _WRITE_AUDIT_OPS:
                self._note(
                    request_id or "x", operation or "?", "authenticated B2 service", exc.code
                )
            token_err = self._crypto.encrypt_error(
                operation or "health", request_id or "x", exc.code, exc.message
            )
            return (200, {"keyId": key_id, "token": token_err}, True)
        except LookupError:
            token_err = self._crypto.encrypt_error(
                operation, request_id, "not_configured", "vector not configured"
            )
            return (200, {"keyId": key_id, "token": token_err}, True)
        except (TransportError, ValueError, KeyError, OSError, RuntimeError):
            if operation in _WRITE_AUDIT_OPS:
                self._note(request_id, operation, "authenticated B2 service", "internal_error")
            token_err = self._crypto.encrypt_error(
                operation, request_id, "internal_error", "bridge request failed"
            )
            return (200, {"keyId": key_id, "token": token_err}, True)
        if operation in _WRITE_AUDIT_OPS:
            actor = "authenticated B2 service"
            if operation == "tasks.ack":
                actor = (
                    "asserted by authenticated B2 service "
                    f"(not independently verified): {args.get('userId', '?')}"
                )
            self._note(request_id, operation, actor, "ok")
        reply = self._crypto.encrypt_response(operation, request_id, result)
        return (200, {"keyId": key_id, "token": reply}, True)

    def _dispatch(self, operation: str, args: dict[str, Any]) -> dict[str, Any]:
        if operation == "health":
            return {"status": "ok", "mode": self._mode}
        if operation == "fhir.read":
            found = self._store.fhir_read(str(args["resourceType"]), str(args["id"]))
            return {"resource": found}
        if operation == "fhir.search":
            items = self._store.fhir_search(str(args["resourceType"]), dict(args["params"]))
            return {"resources": list(items)}
        if operation == "fhir.write":
            if "resource" in args:
                stored = self._store.fhir_write(dict(args["resource"]))
                return {"resource": stored}
            bundle = dict(args["bundle"])
            if bundle.get("type") != "transaction":
                raise ContractError(code="bad_payload", message="only transaction allowed")
            out = self._store.fhir_transaction(bundle)
            if not isinstance(out, dict):
                raise ContractError(code="internal_error", message="bridge request failed")
            return {"bundle": out}
        if operation == "tasks.write":
            task = validate_public_task_create(dict(args["task"]))
            creator = getattr(self._store, "tasks_create", None)
            if creator is None:
                raise ContractError(code="not_configured", message="task create unavailable")
            stored = creator(task)
            return {"task": stored}
        if operation == "tasks.read":
            items = self._store.tasks_read(args.get("taskId"))
            return {"tasks": list(items)}
        if operation == "tasks.ack":
            user = _strict_user(args.get("userId"))
            if self._allowed is not None and user not in self._allowed:
                raise AuthError(code="auth_failed", message="user is not allowlisted")
            try:
                updated = self._store.tasks_ack(str(args["taskId"]), user)
            except KeyError as exc:
                raise ContractError(code="not_found", message="task not found") from exc
            return {"task": updated}
        if operation == "vector.search":
            hits = self._store.vector_search(
                str(args["channel"]), str(args["query"]), int(args["limit"])
            )
            return {"hits": list(hits)}
        if operation in SCREENING_OPERATIONS:
            return dispatch_screening(self._screening, operation, args)
        raise ContractError(code="bad_operation", message="operation not allowed")


class _BaseBridgeHandler(BaseHTTPRequestHandler):
    dispatcher: BridgeDispatcher | None = None
    request_timeout: float = 10.0
    worker_slots: threading.Semaphore | None = None

    def log_message(self, *args: object) -> None:
        return

    def setup(self) -> None:
        super().setup()
        with contextlib.suppress(OSError):
            self.connection.settimeout(type(self).request_timeout)

    def do_GET(self) -> None:
        self._refuse(404)

    def do_PUT(self) -> None:
        self._refuse(404)

    def do_DELETE(self) -> None:
        self._refuse(404)

    def do_PATCH(self) -> None:
        self._refuse(404)

    def _refuse(self, code: int) -> None:
        if code == 404:
            err = {"code": "not_found", "message": "request refused"}
        elif code == 413:
            err = {"code": "too_large", "message": "request refused"}
        elif code == 503:
            err = {"code": "temporarily_unavailable", "message": "request refused"}
        else:
            err = {"code": "bad_envelope", "message": "request refused"}
        body = json.dumps({"error": err}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with contextlib.suppress(OSError):
            self.wfile.write(body)

    def do_POST(self) -> None:
        slots = type(self).worker_slots
        if slots is not None and not slots.acquire(blocking=False):
            self._refuse(503)
            return
        try:
            self._serve_post()
        finally:
            if slots is not None:
                slots.release()

    def _serve_post(self) -> None:
        if self.path != RPC_PATH:
            self._refuse(404)
            return
        encoding = self.headers.get("Transfer-Encoding")
        if encoding is not None:
            self._refuse(400)
            return
        raw_lengths: list[str] = []
        getter = getattr(self.headers, "get_all", None)
        if callable(getter):
            with contextlib.suppress(ValueError, AttributeError):
                raw_lengths = [str(v) for v in (getter("Content-Length") or [])]
        if not raw_lengths:
            single = self.headers.get("Content-Length")
            raw_lengths = [single] if single is not None else []
        if not raw_lengths:
            self._refuse(400)
            return
        if len(raw_lengths) != 1 or "," in raw_lengths[0]:
            self._refuse(400)
            return
        try:
            length = int(raw_lengths[0].strip())
        except ValueError:
            self._refuse(400)
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._refuse(413 if length > MAX_BODY_BYTES else 400)
            return
        try:
            body = self.rfile.read(length)
        except OSError:
            self._refuse(400)
            return
        if len(body) != length:
            self._refuse(400)
            return
        try:
            raw: Any = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._refuse(400)
            return
        dispatcher = self.dispatcher
        assert dispatcher is not None
        status, payload, _enc = dispatcher.handle_outer(raw)
        out = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        with contextlib.suppress(OSError):
            self.wfile.write(out)

    def version_string(self) -> str:
        return "bridge"


def build_server(
    bind: str,
    port: int,
    key_file: Path,
    key_id: str,
    store: Any,
    ttl: int = 60,
    mode: str = "mock",
    allowed_users: frozenset[str] | None = None,
    audit_path: Path | str | None = None,
    request_timeout: float = 10.0,
    max_workers: int = MAX_WORKERS,
    screening: Any | None = None,
) -> ThreadingHTTPServer:
    key = load_key(Path(key_file))
    crypto = BridgeCrypto(key=key, key_id=key_id, ttl=ttl)
    replay = ReplayCache(ttl_seconds=float(ttl + 60))
    audit = file_audit_sink(Path(audit_path)) if audit_path is not None else None
    dispatcher = BridgeDispatcher(
        crypto,
        store,
        replay,
        mode=mode,
        allowed_users=allowed_users,
        audit=audit,
        screening=screening,
    )
    handler_cls = type(
        "BridgeHandler",
        (_BaseBridgeHandler,),
        {
            "dispatcher": dispatcher,
            "request_timeout": request_timeout,
            "worker_slots": threading.Semaphore(max_workers),
        },
    )
    server = ThreadingHTTPServer((bind, port), handler_cls)
    server.daemon_threads = True
    server.timeout = 10.0
    return server


def serve_forever(server: ThreadingHTTPServer) -> None:
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()


def start_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=serve_forever, args=(server,), daemon=True)
    thread.start()
    return thread
