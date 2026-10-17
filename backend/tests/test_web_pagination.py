from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_fhir_pagination import adapter, observation, page
from test_web_service import FakeClient, bundle

from rakathon_backend.b2.collection import bounded_reply
from rakathon_backend.b2.iris.fhir_only import FhirOnlyStorage
from rakathon_backend.common.collection import checked_metadata
from rakathon_backend.common.contracts import DataKind
from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.rpc import new_envelope
from rakathon_backend.runtime.application import BackendApp, fresh_tokens
from rakathon_backend.web.contracts import WebError
from rakathon_backend.web.service import MAX_OBSERVATION_BYTES, MAX_SECTION_BYTES, WebService


async def test_paged_actual_b4_b2_facade_88_and_reference_closure(tmp_path: Path) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/Patient/p"):
            return httpx.Response(200, json={"resourceType": "Patient", "id": "p"})
        if path.endswith("/Observation"):
            second = "cursor" in request.url.params
            items = [observation(i) for i in range(50 if second else 0, 88 if second else 50)]
            return httpx.Response(
                200, json=page(items, None if second else "?cursor=opaque%2Btoken", None)
            )
        if path.endswith("/DiagnosticReport"):
            reports = [
                {
                    "resourceType": "DiagnosticReport",
                    "id": f"report-{i}",
                    "subject": {"reference": "Patient/p"},
                    "result": [{"reference": f"Observation/obs-{i}"}],
                }
                for i in range(34)
            ]
            return httpx.Response(200, json=page(reports, total=34))
        return httpx.Response(200, json=page([], total=0))

    app = BackendApp(
        tmp_path / "uds", fresh_tokens(), store=FhirOnlyStorage(adapter(respond)), mode="iris-fhir"
    )
    await app.start()
    try:
        status, case = await WebService.from_app(app).case("p")
        assert status == 200
        section = case["sections"]["observations"]
        assert section["status"] == "complete" and len(section["items"]) == 88
        assert section["receivedCount"] == section["encounteredCount"] == 88
        assert section["pagesFetched"] == 2 and section["serverTotal"] is None
        refs = {f"Observation/{item['id']}" for item in section["items"]}
        assert all(
            ref["reference"] in refs
            for report in case["sections"]["diagnosticReports"]["items"]
            for ref in report["result"]
        )
        assert len(json.dumps(case).encode()) < 1024 * 1024
    finally:
        await app.close()


async def test_paged_error_metadata_crosses_b2_b4_ipc(tmp_path: Path) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Patient/p"):
            return httpx.Response(200, json={"resourceType": "Patient", "id": "p"})
        if request.url.path.endswith("/Observation"):
            if "cursor" in request.url.params:
                return httpx.Response(403, content=b"PRIVATE")
            return httpx.Response(200, json=page([observation(i) for i in range(50)], "?cursor=2"))
        return httpx.Response(200, json=page([], total=0))

    app = BackendApp(
        tmp_path / "uds", fresh_tokens(), store=FhirOnlyStorage(adapter(respond)), mode="iris-fhir"
    )
    await app.start()
    try:
        case = (await WebService.from_app(app).case("p"))[1]
        section = case["sections"]["observations"]
        assert section == {
            "status": "unavailable",
            "items": [],
            "reason": "auth_failed",
            "receivedCount": 50,
            "encounteredCount": 50,
            "pagesFetched": 1,
            "serverTotal": 88,
        }
        assert "PRIVATE" not in json.dumps(case)
    finally:
        await app.close()


@pytest.mark.parametrize("variant", ["fanout", "nested", "bytes", "root"])
async def test_projection_limits_fail_empty_with_reason(variant: str) -> None:
    client = FakeClient()
    n = 501 if variant == "root" else 20 if variant == "fanout" else 64 if variant == "bytes" else 1
    items = [{**observation(i), "subject": {"reference": "Patient/synthetic-1"}} for i in range(n)]
    if variant in ("fanout", "nested"):
        for item in items:
            item["component"] = [{"valueBoolean": False}] * (50 if variant == "fanout" else 51)
    if variant == "bytes":
        for item in items:
            item["valueString"] = "x" * 4096
    client.responses["Observation"] = bundle(items, n)
    section = (await WebService(client).case("synthetic-1"))[1]["sections"]["observations"]
    assert section["items"] == [] and section["status"] == "unavailable"
    assert section["reason"] == ("invalid_response" if variant == "nested" else "resource_limit")


@pytest.mark.parametrize(
    "resource_type,count,expected",
    [
        ("Observation", 50, "complete"),
        ("Observation", 64, "unavailable"),
        ("Condition", 50, "unavailable"),
    ],
)
async def test_observation_only_larger_section_budget(
    resource_type: str, count: int, expected: str
) -> None:
    client = FakeClient()
    items = [
        {
            "resourceType": resource_type,
            "id": f"synthetic-{i}",
            "subject": {"reference": "Patient/synthetic-1"},
            "code": {"text": "x" * 4096},
        }
        for i in range(count)
    ]
    serialized_bytes = len(json.dumps(items, ensure_ascii=True).encode())
    assert serialized_bytes > MAX_SECTION_BYTES
    assert (serialized_bytes <= MAX_OBSERVATION_BYTES) == (count == 50)
    client.responses[resource_type] = bundle(items, count)
    section_name = "observations" if resource_type == "Observation" else "conditions"
    status, case = await WebService(client).case("synthetic-1")
    section = case["sections"][section_name]
    assert status == 200 and section["status"] == expected
    assert section["items"] == (items if expected == "complete" else [])
    assert section["reason"] == (None if expected == "complete" else "resource_limit")


async def test_case_has_no_obsolete_assistant_preview() -> None:
    client = FakeClient()
    case = (await WebService(client).case("synthetic-1"))[1]
    assert "assistantPreview" not in case


async def test_patient_projection_byte_cap_prevents_section_reads() -> None:
    client = FakeClient()
    client.patient["name"] = [{"text": "x" * 4096}] * 17
    with pytest.raises(WebError) as failure:
        await WebService(client).case("synthetic-1")
    assert failure.value.status == 503
    assert len(client.requests) == 1


@pytest.mark.parametrize(
    "metadata",
    [
        {"url": "private"},
        {"reason": "private"},
        {"receivedCount": -1},
        {"pagesFetched": 11},
        {"receivedCount": True},
    ],
)
def test_error_metadata_allowlist(metadata: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        checked_metadata(metadata)
    with pytest.raises(ValueError):
        ContractError(metadata=metadata)


def test_final_b2_frame_cap_checked_before_ipc() -> None:
    request = new_envelope(
        source="b4", target="b2", action="fhir.read", data_kind=DataKind.FHIR, payload={}
    )
    reply = request.reply(
        source="b2",
        action="fhir.read",
        data_kind=DataKind.FHIR,
        payload={"padding": "x" * (1024 * 1024)},
    )
    with pytest.raises(ContractError) as failure:
        bounded_reply(reply, 1, {})
    assert failure.value.code == "resource_limit" and failure.value.metadata["receivedCount"] == 1
