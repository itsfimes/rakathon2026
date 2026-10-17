from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

from rakathon_backend.b4.router import web_envelope
from rakathon_backend.common.contracts import DataKind
from rakathon_backend.common.errors import ContractError, TransportError
from rakathon_backend.common.ipc import UnixJsonClient
from rakathon_backend.common.review_limits import WEB_REVIEW_HTTP_TIMEOUT
from rakathon_backend.common.rpc import socket_for


def review_import_ready(args: argparse.Namespace) -> bool:
    return str(getattr(args, "storage", "") or "") == "iris-fhir"


def make_review_importer(runtime_dir: Path, web_token: str) -> Any:
    base = Path(runtime_dir)
    token = str(web_token)

    def _checked_receipt(
        reply: Any, approval_id: str, patient_ref: str, expected_count: int
    ) -> dict[str, Any]:
        if str(getattr(reply, "source", "")) != "b4":
            raise TransportError(code="bad_response", message="review reply source invalid")
        if str(getattr(reply, "action", "")) != "document.approve":
            raise TransportError(code="bad_response", message="review reply action invalid")
        if getattr(reply, "data_kind", None) != DataKind.FHIR:
            raise TransportError(code="bad_response", message="review reply kind invalid")
        payload = getattr(reply, "payload", None)
        if not isinstance(payload, dict):
            raise TransportError(code="bad_response", message="review reply invalid")
        bundle = payload.get("bundle")
        stored = payload.get("stored")
        count = payload.get("count")
        mode = payload.get("mode")
        got_approval = payload.get("approvalId")
        got_patient = payload.get("patientRef")
        if not isinstance(bundle, dict):
            raise TransportError(code="bad_response", message="review receipt invalid")
        if bundle.get("resourceType") != "Bundle":
            raise TransportError(code="bad_response", message="review receipt invalid")
        if bundle.get("type") != "transaction-response":
            raise TransportError(code="bad_response", message="review receipt invalid")
        entries = bundle.get("entry")
        if not isinstance(entries, list) or not entries:
            raise TransportError(code="bad_response", message="review receipt invalid")
        if not isinstance(stored, list) or not stored:
            raise TransportError(code="bad_response", message="review counts invalid")
        if any(not isinstance(item, str) or not item for item in stored):
            raise TransportError(code="bad_response", message="review counts invalid")
        if isinstance(count, bool) or not isinstance(count, int):
            raise TransportError(code="bad_response", message="review counts invalid")
        if int(count) != len(stored) or int(count) != len(entries):
            raise TransportError(code="bad_response", message="review counts invalid")
        if expected_count > 0 and int(count) != int(expected_count):
            raise TransportError(code="bad_response", message="review counts invalid")
        if not isinstance(mode, str) or not mode.strip():
            raise TransportError(code="bad_response", message="review mode invalid")
        if str(got_approval) != approval_id:
            raise TransportError(code="bad_response", message="review approval mismatch")
        if str(got_patient) != patient_ref:
            raise TransportError(code="bad_response", message="review patient mismatch")
        return dict(bundle)

    def _import(job_id: str, user_id: str, prepared: dict[str, Any]) -> dict[str, Any]:
        bundle = prepared.get("bundle")
        context = prepared.get("context")
        approval_id = prepared.get("approvalId")
        if not isinstance(bundle, dict) or not isinstance(context, dict):
            raise ContractError(code="bad_payload", message="review claim is invalid")
        if not isinstance(approval_id, str) or not approval_id:
            raise ContractError(code="bad_payload", message="review claim is invalid")
        patient_ref = context.get("patientRef")
        counts = context.get("counts")
        if not isinstance(patient_ref, str) or not patient_ref:
            raise ContractError(code="bad_payload", message="review claim is invalid")
        expected = 0
        if isinstance(counts, dict) and counts:
            total = 0
            for value in counts.values():
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise ContractError(code="bad_payload", message="review claim is invalid")
                total += int(value)
            expected = total
        uid = str(user_id or "").strip()
        if not uid:
            raise ContractError(code="bad_payload", message="verified identity is required")
        request = web_envelope(
            uid,
            "document.approve",
            {"bundle": dict(bundle), "context": dict(context)},
            DataKind.FHIR,
        )
        client = UnixJsonClient(
            socket_for(base, "b4"),
            token=token,
            source="web:auth",
            timeout=WEB_REVIEW_HTTP_TIMEOUT,
        )
        reply = asyncio.run(client.call(request, expect_source="b4"))
        _ = job_id
        return _checked_receipt(reply, str(approval_id), str(patient_ref), expected)

    return _import
