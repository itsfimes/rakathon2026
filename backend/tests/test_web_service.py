from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.common.contracts import DataKind, Envelope, Health
from rakathon_backend.common.errors import ContractError
from rakathon_backend.runtime.application import BackendApp, fresh_tokens
from rakathon_backend.web.projection import ProjectionError, belongs_to, project
from rakathon_backend.web.runtime import serve_app
from rakathon_backend.web.service import WebError, WebService


def bundle(items: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "mode": "iris-fhir",
        "bundle": {"resourceType": "Bundle", "entry": [{"resource": item} for item in items]},
    }
    if total is not None:
        result["serverTotal"] = total
    return result


class FakeClient:
    def __init__(self) -> None:
        self.requests: list[Envelope] = []
        self.patient: dict[str, Any] = {
            "resourceType": "Patient",
            "id": "synthetic-1",
            "name": [{"given": ["Synthetic"], "family": "Example"}],
        }
        self.responses = {
            kind: bundle([])
            for kind in ("Condition", "Observation", "DiagnosticReport", "DocumentReference")
        }
        self.fail: set[str] = set()
        self.ping_down = False
        self.patients_total = 1

    async def ping(self, service: str) -> Health:
        assert service == "b4"
        return Health.DOWN if self.ping_down else Health.HEALTHY

    async def call(self, envelope: Envelope, *, expect_source: str | None = None) -> Envelope:
        self.requests.append(envelope)
        assert (
            envelope.source,
            envelope.user_id,
            envelope.target,
            envelope.action,
            expect_source,
        ) == ("frontend:viewer", "viewer", "b4", "fhir.read", "b4")
        kind = envelope.payload["resourceType"]
        if kind in self.fail:
            raise ContractError(code="truncated", message="must not leak this")
        if kind == "Patient":
            if envelope.payload.get("_summary") == "count":
                payload = bundle([], self.patients_total)
            elif "id" in envelope.payload:
                payload = bundle([self.patient] if envelope.payload["id"] == "synthetic-1" else [])
            else:
                payload = bundle([self.patient], self.patients_total)
        else:
            assert envelope.payload == {
                "resourceType": kind,
                "patient": "Patient/synthetic-1",
                "_count": "50",
            }
            payload = self.responses[kind]
        return envelope.reply(
            source="b4", action=envelope.action, payload=payload, data_kind=DataKind.FHIR
        )


async def test_session_checks_independent_authenticated_count() -> None:
    client = FakeClient()
    service = WebService(client)
    _, body = await service.session()
    assert body["health"] == {"ipc": "up", "database": "up"}
    assert client.requests[0].payload == {"resourceType": "Patient", "_summary": "count"}
    client.fail.add("Patient")
    _, body = await service.session()
    assert body["health"] == {"ipc": "up", "database": "down"}
    client.fail.clear()
    client.ping_down = True
    _, body = await service.session()
    assert body["health"] == {"ipc": "down", "database": "up"}
    assert not body["capabilities"]["assistant"]


async def test_workspace_summary_and_honest_coverage() -> None:
    client = FakeClient()
    service = WebService(client)
    status, body = await service.workspace()
    assert status == 200
    assert body["patients"] == [
        {
            "patientId": "synthetic-1",
            "label": "Synthetic Example",
            "birthDate": None,
            "diagnosis": None,
        }
    ]
    client.patients_total = 51
    status, body = await service.workspace()
    assert status == 200
    assert len(body["patients"]) == 1
    assert body["coverage"]["serverTotal"] == 51
    client.fail.add("Patient")
    status, body = await service.workspace()
    assert status == 503 and body["coverage"]["status"] == "unavailable"
    assert "must not leak" not in str(body)


async def test_workspace_diagnosis_is_source_derived_and_fail_closed() -> None:
    clinical = "http://terminology.hl7.org/CodeSystem/condition-clinical"
    client = FakeClient()
    client.responses["Condition"] = bundle(
        [
            {
                "resourceType": "Condition",
                "id": "c-resolved",
                "subject": {"reference": "Patient/synthetic-1"},
                "clinicalStatus": {"coding": [{"system": clinical, "code": "resolved"}]},
                "code": {
                    "coding": [
                        {"system": "http://snomed.info/sct", "code": "444814009", "display": "Old"}
                    ]
                },
                "onsetDateTime": "2026-01-01",
            },
            {
                "resourceType": "Condition",
                "id": "c-older",
                "subject": {"reference": "Patient/synthetic-1"},
                "clinicalStatus": {"coding": [{"system": clinical, "code": "active"}]},
                "code": {"text": "Synthetic older finding"},
                "onsetDateTime": "2025-01-01",
            },
            {
                "resourceType": "Condition",
                "id": "c-newer",
                "subject": {"reference": "Patient/synthetic-1"},
                "clinicalStatus": {"coding": [{"system": clinical, "code": "active"}]},
                "code": {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "59621000",
                            "display": "Essential hypertension",
                        }
                    ]
                },
                "onsetDateTime": "2025-06-01",
            },
        ],
        3,
    )
    status, body = await WebService(client).workspace()
    assert status == 200
    assert body["patients"][0]["diagnosis"] == {
        "code": "59621000",
        "label": "Essential hypertension",
    }
    client.responses["Condition"] = bundle(
        [
            {
                "resourceType": "Condition",
                "id": "c-resolved",
                "subject": {"reference": "Patient/synthetic-1"},
                "clinicalStatus": {"coding": [{"system": clinical, "code": "resolved"}]},
                "code": {"text": "Synthetic resolved finding"},
            }
        ],
        1,
    )
    status, body = await WebService(client).workspace()
    assert status == 200 and body["patients"][0]["diagnosis"] is None
    client.fail.add("Condition")
    status, body = await WebService(client).workspace()
    assert status == 503 and body["coverage"]["status"] == "unavailable"
    assert body["patients"] == []
    assert "must not leak" not in str(body)


@pytest.mark.parametrize(
    "reference",
    [
        None,
        "Patient/other",
        "https://external/Patient/synthetic-1",
        "urn:uuid:synthetic-1",
        "synthetic-1",
    ],
)
async def test_wrong_unbound_external_association_is_unavailable(reference: str | None) -> None:
    client = FakeClient()
    item: dict[str, Any] = {"resourceType": "Observation", "id": "obs"}
    if reference is not None:
        item["subject"] = {"reference": reference}
    client.responses["Observation"] = bundle([item], 1)
    client.fail.add("Condition")
    status, body = await WebService(client).case("synthetic-1")
    assert status == 200
    assert body["sections"]["observations"]["status"] == "unavailable"
    assert body["sections"]["conditions"]["status"] == "unavailable"
    assert body["sections"]["documents"]["status"] == "complete"


async def test_partial_sections_projection_and_no_fabricated_values() -> None:
    client = FakeClient()
    client.patient.update(
        {
            "identifier": [{"value": "not-browser-safe"}],
            "text": {"div": "<script>bad</script>"},
            "extension": [{"secret": "bad"}],
        }
    )
    observation = {
        "resourceType": "Observation",
        "id": "obs",
        "subject": {"reference": "Patient/synthetic-1"},
        "status": "final",
        "code": {"text": "Synthetic test", "extension": ["bad"]},
        "valueQuantity": {"value": 7, "unit": "test"},
        "meta": {"versionId": "2", "lastUpdated": "2026-01-01"},
        "effectiveDateTime": "2025-01",
        "referenceRange": [{"low": {"value": 1}, "high": {"value": 9}}],
        "text": {"div": "bad"},
    }
    client.responses["Observation"] = bundle([observation], 1)
    client.responses["DocumentReference"] = bundle(
        [
            {
                "resourceType": "DocumentReference",
                "id": "doc",
                "subject": {"reference": "Patient/synthetic-1"},
                "content": [
                    {
                        "attachment": {
                            "title": "Synthetic",
                            "contentType": "application/pdf",
                            "url": "http://internal/secret",
                            "data": "secret",
                        }
                    }
                ],
            }
        ],
        1,
    )
    _, body = await WebService(client).case("synthetic-1")
    assert "identifier" not in body["patient"] and "text" not in body["patient"]
    projected = body["sections"]["observations"]["items"][0]
    assert projected["valueQuantity"] == {"value": 7, "unit": "test"}
    assert projected["meta"] == observation["meta"]
    assert "extension" not in projected["code"] and "text" not in projected
    assert "birthDate" not in body["patient"]
    assert body["sections"]["documents"]["items"][0]["content"] == [
        {"attachment": {"title": "Synthetic", "contentType": "application/pdf"}}
    ]


async def test_unknown_patient_and_mismatching_identity() -> None:
    client = FakeClient()
    with pytest.raises(WebError) as missing:
        await WebService(client).case("unknown")
    assert missing.value.status == 404 and len(client.requests) == 1
    client.patient["id"] = "wrong"
    with pytest.raises(WebError) as mismatch:
        await WebService(client).case("synthetic-1")
    assert mismatch.value.status == 503


@pytest.mark.parametrize("count,total", [(51, 51), (1, 2)])
async def test_duplicate_section_rejected_but_estimate_not_exact(count: int, total: int) -> None:
    client = FakeClient()
    client.responses["Observation"] = bundle(
        [
            {
                "resourceType": "Observation",
                "id": "obs",
                "subject": {"reference": "Patient/synthetic-1"},
            }
        ]
        * count,
        total,
    )
    _, body = await WebService(client).case("synthetic-1")
    section = body["sections"]["observations"]
    assert section["serverTotal"] == total
    assert section["receivedCount"] == count
    if count > 1:
        assert section["status"] == "unavailable" and section["items"] == []
        assert section["reason"] == "duplicate_resource"
    else:
        assert section["status"] == "complete" and len(section["items"]) == 1


def test_projection_bounds_and_conflicting_association() -> None:
    with pytest.raises(ProjectionError):
        project({"resourceType": "Patient", "id": "p", "name": [{"text": "x" * 4097}]}, "Patient")
    assert not belongs_to(
        {"subject": {"reference": "Patient/p"}, "patient": {"reference": "Patient/other"}}, "p"
    )


class CountStore(MemoryStorage):
    closed = False

    def fhir_search_with_total(
        self, resource_type: str, params: dict[str, str]
    ) -> tuple[list[dict[str, Any]], int]:
        assert resource_type == "Patient"
        assert params == {"_summary": "count"}
        return [], 6

    def close(self) -> None:
        self.closed = True


async def test_actual_b4_b6_b2_viewer_count(tmp_path: Path) -> None:
    store = CountStore()
    app = BackendApp(tmp_path / "uds", fresh_tokens(), store=store, mode="iris-fhir")
    await app.start()
    try:
        _, body = await WebService.from_app(app).session()
        assert body["health"] == {"ipc": "up", "database": "up"}
    finally:
        await app.close()


async def test_start_failure_closes_app_store(tmp_path: Path) -> None:
    store = CountStore()
    app = BackendApp(tmp_path / "uds", fresh_tokens(), store=store, mode="iris-fhir")
    with pytest.raises(ValueError):
        await serve_app(app, "0.0.0.0", 0, "key", frozenset(), asyncio.Event())
    assert store.closed
    assert not list((tmp_path / "uds").glob("*.sock"))


async def test_broken_iris_never_uses_mock_and_large_section_isolated() -> None:
    client = FakeClient()
    client.responses["Observation"] = {
        "mode": "mock",
        "bundle": {"resourceType": "Bundle", "entry": []},
    }
    client.responses["DiagnosticReport"] = bundle(
        [
            {
                "resourceType": "DiagnosticReport",
                "id": f"report-{i}",
                "subject": {"reference": "Patient/synthetic-1"},
                "conclusion": "x" * 4096,
            }
            for i in range(50)
        ],
        50,
    )
    _, body = await WebService(client).case("synthetic-1")
    assert body["sections"]["observations"]["status"] == "unavailable"
    assert body["sections"]["diagnosticReports"]["status"] == "unavailable"
    assert body["sections"]["conditions"]["status"] == "complete"


async def test_backend_start_failure_also_closes_store(tmp_path: Path) -> None:
    store = CountStore()
    runtime = tmp_path / "uds"
    runtime.mkdir()
    (runtime / "b6.sock").write_text("blocked")
    app = BackendApp(runtime, fresh_tokens(), store=store, mode="iris-fhir")
    with pytest.raises(OSError):
        await serve_app(app, "127.0.0.1", 0, "key", frozenset(), asyncio.Event())
    assert store.closed
