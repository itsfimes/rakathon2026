from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any, Protocol

from rakathon_backend.b1.docx import DocxError, extract_docx_text, source_urn
from rakathon_backend.b1.translation import attach_source, is_manual_review, validate_bundle
from rakathon_backend.common.blob_store import (
    DOCX_MIME,
    BlobNotFound,
    BlobStore,
    is_blob_ref,
    parse_ref,
)
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError, TransportError
from rakathon_backend.common.fhir import resource_counts

SERVICE_NAME = "b1"
ALLOWED_CALLERS = frozenset({"b4"})
RAW_KEYS = ("blob", "raw", "bytes", "content", "text")


class AuthCheck(Protocol):
    def __call__(self, *, user_id: str, action: str, correlation_id: str) -> Awaitable[bool]: ...


class TranslateViaB5(Protocol):
    def __call__(
        self, *, bytes_ref: str, purpose: str, user_id: str, correlation_id: str
    ) -> Awaitable[dict[str, Any]]: ...


async def _deny_auth(*, user_id: str, action: str, correlation_id: str) -> bool:
    _ = (user_id, action, correlation_id)
    return False


class B1Service:
    def __init__(
        self,
        blob: BlobStore,
        translate_via_b5: TranslateViaB5 | None = None,
        auth_check: AuthCheck | None = None,
    ) -> None:
        self._blob = blob
        self._translate_via_b5 = translate_via_b5
        self._auth_check = auth_check or _deny_auth

    @property
    def blob(self) -> BlobStore:
        return self._blob

    async def handle(self, request: Envelope) -> Envelope:
        if request.target != SERVICE_NAME:
            raise ContractError(code="target_mismatch", message="request target mismatch")
        if request.source not in ALLOWED_CALLERS:
            raise AuthError(code="auth_failed", message="caller is not permitted")
        if request.action != "ingest":
            raise ContractError(code="bad_action", message="unsupported action")
        user_id = request.user_id
        if not user_id or not user_id.strip():
            raise ContractError(code="bad_payload", message="userId is required")
        allowed = await self._auth_check(
            user_id=user_id, action="ingest", correlation_id=request.correlation_id
        )
        if not allowed:
            raise AuthError(code="auth_failed", message="ingest is not permitted")
        payload = request.payload
        ref = payload.get("bytesRef")
        if not isinstance(ref, str) or not ref.strip():
            raise ContractError(code="bad_payload", message="bytesRef is required")
        if not is_blob_ref(ref):
            raise ContractError(code="bad_payload", message="bytesRef scheme is invalid")
        for forbidden in RAW_KEYS:
            if forbidden in payload:
                raise ContractError(code="bad_payload", message="raw blob must not be inlined")
        try:
            parse_ref(ref)
            record = self._blob.get(ref)
        except BlobNotFound as exc:
            raise ContractError(code="blob_not_found", message="blob reference unknown") from exc
        if record.content_type == "application/pdf":
            raise ContractError(code="blob_unsupported_type", message="PDF requires manual review")
        if record.content_type == DOCX_MIME:
            return await self._handle_docx(request, ref, record.data, user_id)
        if record.content_type not in ("text/plain", "application/json"):
            raise ContractError(code="blob_unsupported_type", message="blob type is not supported")
        bundle, mode = await self._via_b5(
            ref, str(payload.get("purpose", "translate")), user_id, request
        )
        return request.reply(
            source=SERVICE_NAME,
            action="ingest",
            payload={"bundle": bundle, "mode": mode},
            data_kind=DataKind.FHIR,
        )

    async def _handle_docx(
        self, request: Envelope, original_ref: str, data: bytes, user_id: str
    ) -> Envelope:
        try:
            extracted = extract_docx_text(data)
        except DocxError as exc:
            raise ContractError(code=exc.code, message=exc.message) from exc
        derived_ref = self._blob.put(extracted.text.encode("utf-8"), "text/plain")
        try:
            bundle, mode = await self._via_b5(
                derived_ref, str(request.payload.get("purpose", "translate")), user_id, request
            )
        finally:
            with suppress(Exception):
                self._blob.delete(derived_ref)
        urn = source_urn(extracted.source_sha256)
        if isinstance(bundle, dict):
            bundle = attach_source(bundle, urn)
        return request.reply(
            source=SERVICE_NAME,
            action="ingest",
            payload={
                "bundle": bundle,
                "mode": mode,
                "sourceHash": extracted.source_sha256,
                "sourceRef": original_ref,
                "sourceUrn": urn,
                "resourceCounts": resource_counts(bundle),
                "manualReview": is_manual_review(bundle),
            },
            data_kind=DataKind.FHIR,
        )

    async def _via_b5(
        self, bytes_ref: str, purpose: str, user_id: str, request: Envelope
    ) -> tuple[dict[str, Any], str]:
        if self._translate_via_b5 is None:
            raise TransportError(code="no_b5_route", message="translation route is not configured")
        try:
            result = await self._translate_via_b5(
                bytes_ref=bytes_ref,
                purpose=purpose,
                user_id=user_id,
                correlation_id=request.correlation_id,
            )
        except (ContractError, AuthError, TransportError):
            raise
        except Exception as exc:
            raise TransportError(code="translate_failed", message="translation failed") from exc
        if not isinstance(result, dict) or "bundle" not in result:
            raise TransportError(code="translate_failed", message="translation returned no bundle")
        bundle = result["bundle"]
        if not isinstance(bundle, dict):
            raise TransportError(code="translate_failed", message="translation bundle invalid")
        if not validate_bundle(bundle):
            raise TransportError(code="translate_failed", message="translation bundle invalid")
        _ = is_manual_review(bundle)
        raw_mode = result.get("mode", "mock")
        mode = raw_mode if isinstance(raw_mode, str) and raw_mode.strip() else "mock"
        return (bundle, mode)


def make_handler(service: B1Service) -> Callable[[Envelope], Awaitable[Envelope]]:
    async def handler(request: Envelope) -> Envelope:
        return await service.handle(request)

    return handler
