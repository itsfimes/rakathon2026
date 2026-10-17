from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_web_service import FakeClient, bundle

from rakathon_backend.b5.direct import DirectAdapter
from rakathon_backend.b5.direct_http import DirectHttpTransport, DirectProviderConfig
from rakathon_backend.common.contracts import DataKind, Envelope, Health
from rakathon_backend.common.errors import AuthError
from rakathon_backend.common.fhir import PATIENT_CONTEXT_TYPES
from rakathon_backend.common.rpc import new_envelope
from rakathon_backend.runtime.application import BackendApp, fresh_tokens
from rakathon_backend.web import assistant as module
from rakathon_backend.web.assistant import validate_request
from rakathon_backend.web.contracts import WebError
from rakathon_backend.web.service import WebService


class AssistantClient:
    def __init__(self) -> None:
        self.requests: list[Envelope] = []
        self.wait = False
        self.answer = "Synthetic answer"

    async def ping(self, service: str) -> Health:
        return Health.HEALTHY

    async def call(self, envelope: Envelope, *, expect_source: str | None = None) -> Envelope:
        assert (envelope.source, envelope.user_id, envelope.action, expect_source) == (
            "frontend:web-assistant",
            "web-assistant",
            "ai.complete",
            "b4",
        )
        self.requests.append(envelope)
        if self.wait:
            await asyncio.Event().wait()
        return envelope.reply(
            source="b4",
            action="ai.complete",
            data_kind=DataKind.PROPRIETARY,
            payload={"mode": "direct", "answer": self.answer},
        )


def fixture_service() -> tuple[WebService, FakeClient, AssistantClient]:
    reader, ai = FakeClient(), AssistantClient()
    reader.responses.update({kind: bundle([]) for kind in PATIENT_CONTEXT_TYPES})
    reader.responses["DiagnosticReport"] = bundle(
        [
            {
                "resourceType": "DiagnosticReport",
                "id": "report-private",
                "subject": {"reference": "Patient/synthetic-1"},
                "code": {"text": "Test report"},
                "conclusion": "PRIVATE BODY DIAGNOSIS",
                "text": {"div": "Full narrative"},
            }
        ]
    )
    return WebService(reader, ai), reader, ai


@pytest.mark.parametrize("role", ["koordinator", "pacient", "lekar", "mdt"])
async def test_full_record_all_roles_and_no_preview(role: str) -> None:
    service, _, ai = fixture_service()
    assert "assistantPreview" not in (await service.case("synthetic-1"))[1]
    status, response = await service.send_assistant(
        {"role": role, "text": "Explain record", "caseId": "synthetic-1"}
    )
    assert status == 200 and response["provenance"] == "server"
    prompt = ai.requests[-1].payload["prompt"]
    for value in (
        "synthetic-1",
        "Synthetic",
        "Example",
        "PRIVATE BODY DIAGNOSIS",
        "Full narrative",
    ):
        assert value in prompt
    assert response["sources"] == ["Patient/synthetic-1", "DiagnosticReport/report-private"]
    assert response["coverage"]["status"] == "complete"


async def test_message_only_and_disabled_health() -> None:
    service, reader, ai = fixture_service()
    response = (await service.send_assistant({"role": "pacient", "text": "General question"}))[1]
    assert response["sources"] == [] and response["coverage"]["status"] == "general"
    assert not reader.requests and len(ai.requests) == 1
    assert (await service.session())[1]["capabilities"]["assistant"]
    reader.ping_down = True
    assert not (await service.session())[1]["capabilities"]["assistant"]
    service.assistant_ready = lambda: False
    with pytest.raises(WebError):
        await service.send_assistant({"role": "pacient", "text": "General question"})


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {},
        {"role": "admin", "text": "Q"},
        {"role": "pacient", "text": " "},
        {"role": "pacient", "text": "x" * 1001},
        *[
            {"role": "pacient", "text": "Q", key: {}}
            for key in ("context", "binding", "userId", "history")
        ],
        *[
            {"role": "pacient", "text": "Q", "caseId": value}
            for value in (None, "", "a/b", "a b", "a" * 65, 42)
        ],
    ],
)
def test_request_validation(raw: Any) -> None:
    with pytest.raises(WebError):
        validate_request(raw)


async def test_busy_deadline_and_local_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _, ai = fixture_service()
    ai.wait = True
    request = {"role": "pacient", "text": "Q"}
    task = asyncio.create_task(service.send_assistant(request))
    await asyncio.sleep(0)
    with pytest.raises(WebError) as busy:
        await service.send_assistant(request)
    assert busy.value.status == 429
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    monkeypatch.setattr(module, "DEADLINE", 0.01)
    with pytest.raises(WebError) as deadline:
        await service.send_assistant(request)
    assert deadline.value.status == 503
    assert service.assistant is not None and not service.assistant.busy


@pytest.mark.parametrize("answer", ["", "x" * 12001])
async def test_invalid_output(answer: str) -> None:
    service, _, ai = fixture_service()
    ai.answer = answer
    with pytest.raises(WebError):
        await service.send_assistant({"role": "pacient", "text": "Q"})


async def test_larger_answer() -> None:
    service, _, ai = fixture_service()
    ai.answer = "x" * 12000
    assert (await service.send_assistant({"role": "pacient", "text": "Q"}))[1]["text"] == ai.answer


async def test_context_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSISTANT_MAX_CONTEXT_BYTES", "100")
    service, _, ai = fixture_service()
    with pytest.raises(WebError) as failure:
        await service.send_assistant({"role": "pacient", "text": "Q", "caseId": "synthetic-1"})
    assert failure.value.status == 413 and failure.value.code == "context_too_large"
    assert not ai.requests


async def test_real_b4_b6_b5_mock_transport_no_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_DISABLED", "0")
    captured: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": "Safe answer"}}]},
        )

    config = DirectProviderConfig(
        "https://synthetic.invalid/openai/v1",
        "test-model",
        "api-key",
        "synthetic-key",
        allow_remote=True,
    )
    transport = DirectHttpTransport(config, transport=httpx.MockTransport(respond))
    app = BackendApp(
        tmp_path / "uds",
        fresh_tokens(),
        ai_adapter=DirectAdapter(transport),
        ai_mode="direct",
        mode="iris-fhir",
    )
    await app.start()
    try:
        service = WebService.from_app(app, True)
        assert (await service.send_assistant({"role": "pacient", "text": "General question"}))[1][
            "text"
        ] == "Safe answer"
        assert "response_format" not in captured[0]
        assert app.store.fhir_search("Patient", {}) == []
        client = app.frontend_client("web-assistant")
        forged = new_envelope(
            source="frontend:web-assistant",
            target="b4",
            action="ai.complete",
            data_kind=DataKind.PROPRIETARY,
            payload={"prompt": "Q"},
            user_id="admin",
        )
        with pytest.raises(AuthError):
            await client.call(forged, expect_source="b4")
        for action in (
            "fhir.read",
            "fhir.write",
            "ingest",
            "ai.translate",
            "tasks.read",
            "tasks.write",
            "health",
            "vector.patient.search",
            "watchdog.tick",
        ):
            request = new_envelope(
                source="frontend:web-assistant",
                target="b4",
                action=action,
                data_kind=DataKind.PROPRIETARY,
                payload={},
                user_id="web-assistant",
            )
            with pytest.raises(AuthError):
                await client.call(request, expect_source="b4")
        await app.kill_switch.trip()
        with pytest.raises(WebError):
            await service.send_assistant({"role": "pacient", "text": "Q"})
        assert len(captured) == 1
    finally:
        await app.close()
