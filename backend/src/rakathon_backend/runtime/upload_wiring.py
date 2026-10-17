from __future__ import annotations

import argparse
import asyncio
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rakathon_backend.b4.router import web_envelope
from rakathon_backend.common.contracts import DataKind
from rakathon_backend.common.errors import ContractError, TransportError
from rakathon_backend.common.ipc import UnixJsonClient
from rakathon_backend.common.kinds import request_kind
from rakathon_backend.common.rpc import new_envelope, socket_for
from rakathon_backend.runtime.review_bridge import make_review_importer, review_import_ready
from rakathon_backend.uploads.crypto import generate_key_file as _gen_key
from rakathon_backend.uploads.crypto import load_key_file as _load_key
from rakathon_backend.uploads.http import UploadRoutes
from rakathon_backend.uploads.review_http import ReviewUploadRoutes
from rakathon_backend.uploads.review_store import ReviewStore
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.uploads.worker import UploadWorker, launcher_secret_ok
from rakathon_backend.web.router import AuthHTTPRouter


def maybe_build_uploads(
    args: argparse.Namespace,
    runtime_dir: Path,
    web_token: str,
    router: AuthHTTPRouter,
    *,
    set_assistant_uploads: Callable[[UploadStore], None] | None = None,
) -> Any:
    enabled = bool(getattr(args, "converter_enable", False))
    store_raw = str(getattr(args, "converter_store", "") or "")
    secret_raw = str(getattr(args, "converter_secret_file", "") or "")
    image = str(getattr(args, "converter_image", "") or "rakathon-converter:latest")
    if not enabled:
        router.set_upload_handler(None)
        return None
    if not store_raw:
        raise ContractError(
            code="converter_store_required", message="converter store is required when enabled"
        )
    store_path = Path(store_raw)
    if store_path.is_symlink():
        raise ContractError(
            code="converter_store_required", message="converter store must not be a symlink"
        )
    try:
        runtime_resolved = runtime_dir.resolve()
        store_resolved = store_path.resolve() if store_path.exists() else store_path.absolute()
    except OSError as exc:
        raise ContractError(
            code="converter_store_required", message="converter store is not usable"
        ) from exc
    if store_resolved == runtime_resolved or runtime_resolved in store_resolved.parents:
        raise ContractError(
            code="converter_store_required",
            message="converter store must live outside the runtime dir",
        )
    store_path.mkdir(parents=True, mode=0o700, exist_ok=True)
    key_path = store_path / "store.key"
    try:
        if key_path.exists():
            keys = _load_key(key_path)
        else:
            keys = _gen_key(key_path)
    except ContractError as exc:
        raise ContractError(
            code="converter_key_required", message="converter store key is not usable"
        ) from exc
    store = UploadStore(store_path, keys)
    if set_assistant_uploads is not None:
        set_assistant_uploads(store)
    if secret_raw:
        sec = Path(secret_raw)
        if sec.is_symlink():
            raise ContractError(
                code="converter_key_required", message="converter secret must not be a symlink"
            )
        try:
            mode = sec.stat().st_mode
        except OSError as exc:
            raise ContractError(
                code="converter_key_required", message="converter secret is not readable"
            ) from exc
        if not stat.S_ISREG(mode) or (mode & 0o077) != 0:
            raise ContractError(
                code="converter_key_required", message="converter secret must be owner-only 0600"
            )
    try:
        key_ok = launcher_secret_ok(secret_raw if secret_raw else None)
    except (OSError, ValueError):
        key_ok = False
    recipe_dir = store_path / "recipes-only"
    recipe_dir.mkdir(mode=0o700, exist_ok=True)
    worker = UploadWorker(
        store,
        secret_file=secret_raw if secret_raw else None,
        image=image,
        recipe_cache=recipe_dir / "recipes.json",
    )

    def _authorize(user_id: str, action: str) -> bool:
        req = new_envelope(
            source="web:auth",
            target="b6",
            action="authorize",
            data_kind=DataKind.METADATA,
            payload={"userId": user_id, "action": action},
            user_id=user_id,
        )
        client = UnixJsonClient(
            socket_for(runtime_dir, "b6"), token=web_token, source="web:auth", timeout=5.0
        )
        try:
            reply = asyncio.run(client.call(req, expect_source="b6"))
        except (
            ContractError,
            TransportError,
            OSError,
            TimeoutError,
            ValueError,
            KeyError,
            RuntimeError,
            AttributeError,
        ):
            return False
        try:
            return reply.payload.get("allowed") is True
        except (AttributeError, ValueError, TypeError):
            return False

    def _case_access(user_id: str, case_id: str) -> bool | None:
        req = web_envelope(
            user_id,
            "fhir.read",
            {"resourceType": "Patient", "id": case_id},
            request_kind("fhir.read"),
        )
        client = UnixJsonClient(
            socket_for(runtime_dir, "b4"), token=web_token, source="web:auth", timeout=7.0
        )
        try:
            reply = asyncio.run(client.call(req, expect_source="b4"))
        except (
            ContractError,
            TransportError,
            OSError,
            TimeoutError,
            ValueError,
            KeyError,
            RuntimeError,
            AttributeError,
        ):
            return None
        try:
            payload = reply.payload
            bundle = payload.get("bundle")
            if not isinstance(bundle, dict):
                return None
            entries = bundle.get("entry", [])
            if not isinstance(entries, list) or not entries:
                return False
            for entry in entries:
                res = entry.get("resource", {}) if isinstance(entry, dict) else {}
                if isinstance(res, dict) and res.get("id") == case_id:
                    return True
            return False
        except (AttributeError, ValueError, TypeError):
            return None

    routes = UploadRoutes(
        store,
        worker,
        authorize=_authorize,
        case_access=_case_access,
        ai_available=lambda: bool(key_ok),
    )
    reviews = ReviewStore(store)
    importer = make_review_importer(runtime_dir, web_token)

    def _import_ready() -> bool:
        return review_import_ready(args)

    def _approve_auth(user_id: str) -> bool:
        return _authorize(user_id, "document.approve")

    wrapper = ReviewUploadRoutes(
        routes,
        reviews,
        authorize_approve=_approve_auth,
        import_ready=_import_ready,
        importer=importer,
    )

    def _handle(
        identity: Any, method: str, path: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, dict[str, str], Any]:
        out = wrapper.handle(str(identity.user_id), str(identity.role), method, path, headers, body)
        if out is None:
            return (404, {}, {"version": 1, "error": {"code": "not_found", "message": "not found"}})
        return out

    router.set_upload_handler(_handle)
    return worker
