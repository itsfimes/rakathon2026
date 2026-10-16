from __future__ import annotations

import asyncio
import copy
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
from rakathon_backend.common.rpc import new_envelope
from rakathon_backend.runtime.application import BackendApp, fresh_tokens
from rakathon_backend.web import assistant as module
from rakathon_backend.web.assistant import validate_request
from rakathon_backend.web.assistant_context import SnapshotBindings
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
    reader.responses["DiagnosticReport"] = bundle(
        [
            {
                "resourceType": "DiagnosticReport",
                "id": "report-private",
                "subject": {"reference": "Patient/synthetic-1"},
                "code": {"text": "Test report"},
                "issued": "2026-01-01",
                "status": "final",
                "conclusion": "PRIVATE BODY DIAGNOSIS",
                "meta": {"versionId": "1"},
            }
        ],
        1,
    )
    return WebService(reader, ai), reader, ai


async def test_exact_preview_context_only_reaches_b4() -> None:
    service, _, ai = fixture_service()
    _, case = await service.case("synthetic-1")
    for role, preview in case["assistantPreview"].items():
        request = {"role": role, "text": "Explain supplied metadata", **preview}
        status, response = await service.send_assistant(request)
        assert status == 200 and response["provenance"] == "server"
        prompt = ai.requests[-1].payload["prompt"]
        data = json.loads(prompt.split("BEGIN DATA\n")[1].split("\nEND DATA")[0])
        assert data["context"] == preview["context"]
        assert set(data) == {"role", "message", "context"}
        for private in (
            "synthetic-1",
            "Synthetic",
            "Example",
            "report-private",
            "PRIVATE BODY",
            preview["binding"]["token"],
        ):
            assert private not in prompt
        assert set(response["sources"]) == {field["source"] for field in data["context"]["fields"]}
        if role == "koordinator":
            assert len(data["context"]["fields"]) == 1


async def test_message_only_and_disabled_health() -> None:
    service, reader, ai = fixture_service()
    assert (await service.send_assistant({"role": "pacient", "text": "General question"}))[1][
        "sources"
    ] == []
    assert not reader.requests and len(ai.requests) == 1
    assert (await service.session())[1]["capabilities"]["assistant"]
    reader.ping_down = True
    assert not (await service.session())[1]["capabilities"]["assistant"]
    service.assistant_ready = lambda: False
    with pytest.raises(WebError):
        await service.send_assistant({"role": "pacient", "text": "General question"})
    assert "assistantPreview" not in (await service.case("synthetic-1"))[1]


async def test_report_metadata_excludes_private_labels_and_limits_three() -> None:
    service, reader, _ = fixture_service()
    template = reader.responses["DiagnosticReport"]["bundle"]["entry"][0]["resource"]
    reader.responses["DiagnosticReport"] = bundle(
        [
            {**template, "id": f"report-{index}", "code": {"text": title}}
            for index, title in enumerate(
                [
                    "Synthetic Example",
                    "Patient/synthetic-1",
                    "Known condition",
                    "Metadata A",
                    "Metadata B",
                    "Metadata C",
                    "Metadata D",
                ]
            )
        ],
        7,
    )
    reader.responses["Condition"] = bundle(
        [
            {
                "resourceType": "Condition",
                "id": "condition",
                "subject": {"reference": "Patient/synthetic-1"},
                "code": {"text": "Known condition"},
            }
        ],
        1,
    )
    fields = (await service.case("synthetic-1"))[1]["assistantPreview"]["pacient"]["context"][
        "fields"
    ]
    assert len(fields) == 4
    assert [item["value"].split(" · ")[0] for item in fields[1:]] == [
        "Metadata A",
        "Metadata B",
        "Metadata C",
    ]


@pytest.mark.parametrize(
    "change", ["context", "case", "role", "token", "version", "coverage", "expiry"]
)
async def test_binding_tamper_and_stale_never_dispatch(change: str) -> None:
    service, reader, ai = fixture_service()
    assert service.assistant is not None
    clock = [1000.0]
    service.assistant.bindings = SnapshotBindings(lambda: clock[0])
    case = (await service.case("synthetic-1"))[1]
    request = {
        "role": "pacient",
        "text": "Question",
        **copy.deepcopy(case["assistantPreview"]["pacient"]),
    }
    if change == "context":
        request["context"]["fields"][0]["value"] = "Forged coverage"
    elif change == "case":
        request["binding"]["caseId"] = "other"
    elif change == "role":
        request["role"] = request["context"]["role"] = "mdt"
    elif change == "token":
        request["binding"]["token"] = "1000." + "0" * 64
    elif change == "version":
        reader.responses["DiagnosticReport"]["bundle"]["entry"][0]["resource"]["meta"][
            "versionId"
        ] = "2"
    elif change == "coverage":
        reader.fail.add("Observation")
    else:
        clock[0] += 301
    with pytest.raises(WebError):
        await service.send_assistant(request)
    assert not ai.requests


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {},
        {"role": "admin", "text": "Q"},
        {"role": "pacient", "text": " "},
        {"role": "pacient", "text": "x" * 1001},
        {"role": "pacient", "text": "Q", "history": []},
        {"role": "pacient", "text": "Q", "context": {}},
        {"role": "pacient", "text": "Q", "binding": {}},
    ],
)
def test_request_validation(raw: Any) -> None:
    with pytest.raises(WebError):
        validate_request(raw)


@pytest.mark.parametrize(
    "mutation", ["fields", "value", "total", "source", "unknown", "coordinator"]
)
async def test_context_allowlist_bounds(mutation: str) -> None:
    service, _, ai = fixture_service()
    preview = (await service.case("synthetic-1"))[1]["assistantPreview"]["pacient"]
    request = {"role": "pacient", "text": "Q", **preview}
    field = request["context"]["fields"][0]
    if mutation == "fields":
        request["context"]["fields"] = [field] * 33
    elif mutation == "value":
        field["value"] = "x" * 321
    elif mutation == "total":
        request["context"]["fields"] = [{**field, "value": "x" * 320}] * 13
    elif mutation == "source":
        field["source"] = "diagnoses"
    elif mutation == "unknown":
        field["id"] = "private"
    else:
        request["role"] = request["context"]["role"] = "koordinator"
    with pytest.raises(WebError):
        await service.send_assistant(request)
    assert not ai.requests


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


@pytest.mark.parametrize("answer", ["", "x" * 6001])
async def test_invalid_output(answer: str) -> None:
    service, _, ai = fixture_service()
    ai.answer = answer
    with pytest.raises(WebError):
        await service.send_assistant({"role": "pacient", "text": "Q"})


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
        assert (
            await service.send_assistant({"role": "pacient", "text": "General synthetic question"})
        )[1]["text"] == "Safe answer"
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
