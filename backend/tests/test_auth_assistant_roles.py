from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_auth_bridge_merge import PW, auth_headers, call_router, login_pair, make_stack

from rakathon_backend.common.contracts import Envelope
from rakathon_backend.web import auth_bridge
from rakathon_backend.web.auth_bridge import IdentityClient


@pytest.mark.parametrize(
    "view,role",
    [
        ("koordinator", "coordinator"),
        ("lekar", "clinician"),
        ("mdt", "clinician"),
        ("pacient", "viewer"),
    ],
)
async def test_all_views_have_capability_and_general_and_selected_case_assistant(
    tmp_path: Path, view: str, role: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = await make_stack(tmp_path, ai_mode="direct", assistant=True)
    try:
        store = stack["app"].store

        def counted_search(kind: str, params: dict[str, str]) -> tuple[list[dict[str, Any]], int]:
            items = store.fhir_search(kind, params)
            return items, len(items)

        # Match real IRIS count metadata, which capability health requires.
        monkeypatch.setattr(store, "fhir_search_with_total", counted_search)
        username = f"assistant.{view}"
        stack["svc"].provision_user(username, PW, role)
        token, csrf = await login_pair(stack, username)
        status, session = await call_router(
            stack["router"], "GET", "/api/v1/session", auth_headers(token), None
        )
        assert status == 200 and session["capabilities"]["assistant"] is True
        for selected in (False, True):
            request: dict[str, Any] = {"role": view, "text": "Question"}
            if selected:
                request["caseId"] = "synthetic-1"
            body = json.dumps(request).encode()
            status, reply = await call_router(
                stack["router"], "POST", "/api/v1/assistant", auth_headers(token, csrf, body), body
            )
            assert status == 200 and reply["provenance"] == "server"
            assert reply["coverage"]["status"] == ("complete" if selected else "general")
            assert reply["sources"] == (["Patient/synthetic-1"] if selected else [])
    finally:
        await stack["app"].close()


async def test_human_permission_check_still_fails_closed_before_reads_or_ai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = await make_stack(tmp_path, ai_mode="direct", assistant=True)
    calls: list[Envelope] = []

    async def denied(*args: Any, **kwargs: Any) -> bool:
        return False

    async def forbidden_call(
        self: IdentityClient, request: Envelope, *, expect_source: str | None = None
    ) -> Envelope:
        calls.append(request)
        raise AssertionError("Denied human must not collect records or dispatch AI")

    monkeypatch.setattr(auth_bridge, "human_may_ask", denied)
    monkeypatch.setattr(IdentityClient, "call", forbidden_call)
    try:
        token, csrf = await login_pair(stack, "viewer.one")
        body = json.dumps({"role": "pacient", "text": "Q", "caseId": "synthetic-1"}).encode()
        status, _ = await call_router(
            stack["router"], "POST", "/api/v1/assistant", auth_headers(token, csrf, body), body
        )
        assert status == 403 and not calls
    finally:
        await stack["app"].close()
