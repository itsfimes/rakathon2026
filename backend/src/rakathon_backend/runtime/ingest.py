from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import shutil
import stat
from contextlib import suppress
from pathlib import Path
from typing import Any

from rakathon_backend.b5.direct import DirectAdapter, direct_config_from_env
from rakathon_backend.b5.direct_http import DirectHttpTransport
from rakathon_backend.b5.gateway import AIAdapter
from rakathon_backend.b5.safety import configured_kill_file
from rakathon_backend.common.ai_limits import AI_EDGE_TIMEOUT
from rakathon_backend.common.blob_store import DOCX_MIME, MAX_BLOB_BYTES
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.fhir import is_manual_review, resource_counts
from rakathon_backend.common.kinds import request_kind
from rakathon_backend.common.rpc import make_client, new_envelope
from rakathon_backend.runtime.ai_factory import ai_config_from_env, start_ai_adapter
from rakathon_backend.runtime.application import BackendApp, fresh_tokens
from rakathon_backend.runtime.iris_fhir import build_iris_fhir_app
from rakathon_backend.runtime.paths import short_runtime

SUFFIX_MIMES = {".docx": DOCX_MIME, ".txt": "text/plain", ".json": "application/json"}
MOCK_TIMEOUT = 60.0


def _error(message: str) -> int:
    print(json.dumps({"error": message}))
    return 2


def _read_input(raw_path: str) -> tuple[bytes, str]:
    target = Path(raw_path)
    try:
        info = os.lstat(target)
    except OSError as exc:
        raise ContractError(code="input_unreadable", message="input file is not readable") from exc
    if stat.S_ISLNK(info.st_mode):
        raise ContractError(code="input_unreadable", message="input file must not be a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise ContractError(code="input_unreadable", message="input file is not a regular file")
    if info.st_size > MAX_BLOB_BYTES:
        raise ContractError(code="input_too_large", message="input file exceeds the size cap")
    suffix = target.suffix.lower()
    mime = SUFFIX_MIMES.get(suffix)
    if mime is None:
        raise ContractError(code="input_unsupported", message="input suffix is not supported")
    try:
        with open(target, "rb") as handle:
            data = handle.read(MAX_BLOB_BYTES + 1)
    except OSError as exc:
        raise ContractError(code="input_unreadable", message="input file is not readable") from exc
    if len(data) > MAX_BLOB_BYTES:
        raise ContractError(code="input_too_large", message="input file exceeds the size cap")
    if not data:
        raise ContractError(code="input_unreadable", message="input file is empty")
    return (data, mime)


def _write_output_file(raw_path: str, payload: dict[str, Any]) -> None:
    target = Path(raw_path)
    try:
        if os.path.lexists(target):
            raise ContractError(code="output_refused", message="output file must not exist")
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError(code="output_refused", message="output file is not safe") from exc
    try:
        os.write(fd, (json.dumps(payload, indent=2) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _owned_runtime(explicit: str | None) -> tuple[Path, bool]:
    if explicit:
        base = Path(explicit)
        if not base.is_dir() or base.is_symlink():
            raise ContractError(code="runtime_refused", message="runtime dir is not usable")
        owned = base / f"ingest-{secrets.token_hex(8)}"
        try:
            owned.mkdir(mode=0o700, parents=False, exist_ok=False)
        except OSError as exc:
            raise ContractError(
                code="runtime_refused", message="runtime dir is not usable"
            ) from exc
        return (owned, True)
    return (short_runtime(None), True)


async def cmd_ingest_file(args: argparse.Namespace) -> int:
    user = str(getattr(args, "user", "") or "").strip()
    if not user:
        return _error("user is required")
    ai_mode = str(getattr(args, "ai", "mock") or "mock")
    if ai_mode not in ("mock", "opencode", "direct"):
        return _error("ai mode must be mock, opencode or direct")
    if getattr(args, "storage", "mock") != "mock":
        return _error("live_import_not_configured")
    try:
        data, mime = _read_input(str(args.path))
    except ContractError as exc:
        return _error(exc.code)
    try:
        runtime_dir, _ = _owned_runtime(getattr(args, "runtime_dir", None))
    except ContractError as exc:
        return _error(exc.code)
    adapter: AIAdapter | None = None
    kill_file = configured_kill_file() if ai_mode != "mock" else None
    if ai_mode == "direct":
        try:
            adapter = DirectAdapter(DirectHttpTransport(direct_config_from_env()))
        except (ContractError, TransportError, ValueError):
            shutil.rmtree(runtime_dir, ignore_errors=True)
            return _error("ai_not_configured")
    if ai_mode == "opencode":
        config = ai_config_from_env()
        kill_file = Path(config.kill_file) if config.kill_file else None
        if not config.ready:
            shutil.rmtree(runtime_dir, ignore_errors=True)
            print(json.dumps({"error": "ai_not_configured", "blockers": list(config.blockers)}))
            return 2
        try:
            adapter = await start_ai_adapter(config)
        except (ContractError, TransportError, OSError, ValueError) as exc:
            shutil.rmtree(runtime_dir, ignore_errors=True)
            print(json.dumps({"error": "ai_startup_failed", "message": str(exc)}))
            return 2
    try:
        if getattr(args, "storage", "mock") == "iris-fhir":
            app = build_iris_fhir_app(
                runtime_dir, fresh_tokens(), adapter=adapter, ai_mode=ai_mode, kill_file=kill_file
            )
        else:
            app = BackendApp(
                runtime_dir,
                fresh_tokens(),
                ai_adapter=adapter,
                ai_mode=ai_mode,
                kill_file=kill_file,
            )
    except (OSError, ValueError, RuntimeError):
        if adapter is not None:
            await adapter.close()
        shutil.rmtree(runtime_dir, ignore_errors=True)
        return _error("storage_not_configured")
    try:
        await app.start()
    except (ContractError, TransportError, OSError, ValueError, RuntimeError) as exc:
        await _close_app(app)
        shutil.rmtree(runtime_dir, ignore_errors=True)
        print(json.dumps({"error": "serve_startup_failed", "message": str(exc)}))
        if adapter is not None:
            with suppress(OSError, RuntimeError):
                await adapter.close()
        return 1
    try:
        summary = await _run_ingest(
            app, data, mime, user, ai_mode, getattr(args, "patient_id", None)
        )
    except (AuthError, ContractError, TransportError, OSError, TimeoutError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}))
        return 1
    except (ValueError, RuntimeError, TypeError):
        print(json.dumps({"error": "ingest_failed"}))
        return 1
    finally:
        try:
            await _close_app(app)
        finally:
            shutil.rmtree(runtime_dir, ignore_errors=True)
    print(json.dumps(summary, indent=2))
    output_file = getattr(args, "output_file", None)
    if output_file:
        try:
            _write_output_file(str(output_file), summary)
        except ContractError as exc:
            print(json.dumps({"error": exc.code}))
            return 2
    return 0


async def _close_app(app: BackendApp) -> None:
    try:
        await app.close()
    finally:
        close = getattr(app.store, "close", None)
        if callable(close):
            await asyncio.to_thread(close)


async def _run_ingest(
    app: BackendApp, data: bytes, mime: str, user: str, ai_mode: str, patient_id: str | None = None
) -> dict[str, Any]:
    source = f"frontend:{user}"
    token = app.tokens.get(source)
    if not token:
        raise AuthError(code="auth_failed", message="unknown user")
    timeout = AI_EDGE_TIMEOUT if ai_mode != "mock" else MOCK_TIMEOUT
    client = make_client(app.runtime_dir, target="b4", source=source, token=token, timeout=timeout)
    original_ref = app.blob.put(data, mime)
    request = new_envelope(
        source=source,
        target="b4",
        action="ingest",
        data_kind=request_kind("ingest"),
        payload={
            "bytesRef": original_ref,
            "purpose": "translate",
            **({"patientId": patient_id} if patient_id is not None else {}),
        },
        user_id=user,
    )
    reply = await client.call(request, expect_source="b4")
    bundle = reply.payload.get("bundle")
    if not isinstance(bundle, dict) and not (
        ai_mode == "direct" and reply.payload.get("status") == "manual-review" and bundle is None
    ):
        raise TransportError(code="translate_failed", message="translation returned no bundle")
    mode = reply.payload.get("mode", "mock")
    counts = resource_counts(bundle)
    manual = reply.payload.get("needsReview", is_manual_review(bundle))
    stored: list[str] = []
    eligible = reply.payload.get("writeEligible", not manual)
    if eligible is True and isinstance(bundle, dict) and bundle.get("resourceType") == "Bundle":
        write_payload: dict[str, Any] = dict(bundle)
        if ai_mode == "direct":
            write_payload = {
                "bundle": bundle,
                "ingestion": {
                    key: reply.payload[key]
                    for key in ("status", "issues", "sourceUrn", "patientId")
                },
            }
        store_request = new_envelope(
            source=source,
            target="b4",
            action="fhir.write",
            data_kind=request_kind("fhir.write"),
            payload=write_payload,
            user_id=user,
        )
        try:
            stored_reply = await client.call(store_request, expect_source="b4")
            raw_stored = stored_reply.payload.get("stored", [])
            if isinstance(raw_stored, list):
                stored = [str(item) for item in raw_stored if isinstance(item, str)]
        except (AuthError, ContractError, TransportError, OSError, TimeoutError) as exc:
            raise TransportError(
                code="write_failed", message="Ingestion persistence failed"
            ) from exc
        if len(stored) != len(bundle["entry"]):
            raise TransportError(code="write_failed", message="Ingestion persistence unconfirmed")
    summary: dict[str, Any] = {
        "sha256": digest_of(data),
        "mode": mode if isinstance(mode, str) else "mock",
        "storage": app.mode,
        "resourceCounts": counts,
        "manualReview": manual,
        "needsReview": manual,
        "writeEligible": eligible,
        "status": reply.payload.get("status", "manual-review" if manual else "complete"),
        "issues": reply.payload.get("issues", []),
        "stored": stored,
        "storedCount": len(stored),
        "persistence": "stored" if stored else "not-written",
        "blobLifecycle": "ephemeral-owner-cleaned",
    }
    if ai_mode == "direct":
        summary.pop("stored", None)
        summary["issues"] = [
            {"code": item["code"], "resourceType": item["resourceType"]}
            for item in reply.payload["issues"]
        ]
        summary["sourceUrn"] = reply.payload.get("sourceUrn")
    source_hash = reply.payload.get("sourceHash")
    if isinstance(source_hash, str) and source_hash:
        summary["sourceHash"] = source_hash
    return summary


def digest_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
