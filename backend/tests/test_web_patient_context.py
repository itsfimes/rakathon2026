from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_fhir_pagination import adapter, observation, page
from test_web_assistant import fixture_service
from test_web_service import bundle

from rakathon_backend.b2.iris.fhir_only import FhirOnlyStorage
from rakathon_backend.b5.direct import DirectAdapter
from rakathon_backend.b5.direct_http import DirectHttpTransport, DirectProviderConfig
from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.fhir import PATIENT_CONTEXT_TYPES
from rakathon_backend.runtime.application import BackendApp, fresh_tokens
from rakathon_backend.converter.model_draft import build_model_draft
from rakathon_backend.uploads.crypto import generate_key_file
from rakathon_backend.uploads.review_helpers import REVIEW_APPROVED_BLOB, REVIEW_STATE_BLOB
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.web.assistant_context import canonical
from rakathon_backend.web.contracts import WebError
from rakathon_backend.web.service import WebService


async def test_full_types_pagination_and_documents_reach_provider(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []
    paths: list[str] = []

    def fhir(request: httpx.Request) -> httpx.Response:
        paths.append(str(request.url))
        kind = request.url.path.rsplit("/", 1)[-1]
        if request.url.path.endswith("/Patient/p"):
            return httpx.Response(
                200,
                json={
                    "resourceType": "Patient",
                    "id": "p",
                    "text": {"div": "PATIENT NARRATIVE"},
                    "extension": [{"url": "urn:custom", "valueString": "FULL EXTENSION"}],
                },
            )
        if kind == "Observation":
            second = "cursor" in request.url.params
            items = [
                {**observation(i), "note": [{"text": "OBSERVATION NOTE"}]}
                for i in range(50 if second else 0, 88 if second else 50)
            ]
            return httpx.Response(200, json=page(items, None if second else "?cursor=2", 88))
        if kind == "ImagingStudy":
            return httpx.Response(404)
        resource: dict[str, Any] = {
            "resourceType": kind,
            "id": "r",
            "subject": {"reference": "Patient/p"},
            "note": [{"text": f"FULL {kind}"}],
        }
        if kind == "DocumentReference":
            resource["content"] = [
                {
                    "attachment": {
                        "contentType": "text/plain",
                        "data": base64.b64encode(b"DOCUMENT TEXT").decode(),
                    }
                },
                {"attachment": {"contentType": "application/pdf", "data": "AA=="}},
                {
                    "attachment": {
                        "contentType": "text/plain",
                        "url": "https://never-fetch.invalid/secret",
                    }
                },
            ]
        if kind == "DiagnosticReport":
            resource["conclusion"] = "FULL CONCLUSION"
            resource["presentedForm"] = [
                {
                    "contentType": "application/json",
                    "data": base64.b64encode(b'{"report":"PRESENTED TEXT"}').decode(),
                }
            ]
        return httpx.Response(200, json=page([resource], total=1))

    def provider(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": "Answer"}}]}
        )

    transport = DirectHttpTransport(
        DirectProviderConfig(
            "https://provider.invalid/openai/v1", "model", "api-key", "test", allow_remote=True
        ),
        transport=httpx.MockTransport(provider),
    )
    storage = FhirOnlyStorage(adapter(fhir))
    app = BackendApp(
        tmp_path / "uds",
        fresh_tokens(),
        store=storage,
        mode="iris-fhir",
        ai_adapter=DirectAdapter(transport),
        ai_mode="direct",
    )
    await app.start()
    try:
        response = (
            await WebService.from_app(app, True).send_assistant(
                {"role": "koordinator", "text": "Q", "caseId": "p"}
            )
        )[1]
        prompt = captured[0]["messages"][0]["content"]
        for text in (
            "PATIENT NARRATIVE",
            "FULL EXTENSION",
            '"id":"obs-87"',
            "OBSERVATION NOTE",
            "FULL CONCLUSION",
            "DOCUMENT TEXT",
            "PRESENTED TEXT",
            "binary, not readable",
            "unsupported_type",
        ):
            assert text in prompt
        for kind in PATIENT_CONTEXT_TYPES:
            if kind not in ("Observation", "ImagingStudy"):
                assert f"FULL {kind}" in prompt
        assert len(response["sources"]) == 50
        assert response["coverage"]["failedTypes"] == ["ImagingStudy"]
        assert response["coverage"]["unreadableAttachments"] == 2
        assert response["coverage"]["status"] == "partial"
        assert all("never-fetch" not in path and "$everything" not in path for path in paths)
        assert len([path for path in paths if "/Observation?" in path]) == 2
        assert len(canonical({"prompt": prompt})) < 4_194_304
    finally:
        await app.close()


async def test_other_owner_same_case_uploads_read_only(tmp_path: Path) -> None:
    store = UploadStore(tmp_path / "store", generate_key_file(tmp_path / "key"))
    first = store.enqueue("human-one", "synthetic-1", "first.txt", b"first")
    second = store.enqueue("human-two", "synthetic-1", "second.txt", b"second")
    other = store.enqueue("human-two", "other-patient", "other.txt", b"other")
    transcript = {
        "version": 1,
        "sourceSha256": second["sha256"],
        "untrusted": True,
        "method": "opencode-native-files",
        "modelOutputText": "UNVERIFIED TRANSCRIPT",
        "pages": ["PAGE TEXT"],
        "extractSha256": None,
    }
    store.write_result_blob(second["id"], "transcription", canonical(transcript))
    store.write_result_blob(second["id"], "model-draft", canonical(
        build_model_draft("PENDING RAW DRAFT", second["sha256"], "test", "test")
    ))
    approved = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "approved",
                    "subject": {"reference": "Patient/synthetic-1"},
                    "valueString": "APPROVED RESULT",
                }
            }
        ],
    }
    store.write_result_blob(first["id"], REVIEW_APPROVED_BLOB, canonical(approved))
    store.write_result_blob(
        first["id"],
        REVIEW_STATE_BLOB,
        canonical(
            {
                "caseId": "synthetic-1",
                "state": "importing",
                "candidateText": "",
            }
        ),
    )
    store.write_result_blob(
        other["id"], REVIEW_APPROVED_BLOB, canonical({"secret": "OTHER CASE SECRET"})
    )
    before = {str(path): path.read_bytes() for path in store.root.rglob("*") if path.is_file()}
    service, reader, ai = fixture_service()
    service = WebService(reader, ai, uploads=store)
    response = (
        await service.send_assistant({"role": "pacient", "text": "Q", "caseId": "synthetic-1"})
    )[1]
    prompt = ai.requests[0].payload["prompt"]
    for text in (
        "UNVERIFIED TRANSCRIPT",
        "PAGE TEXT",
        "APPROVED RESULT",
        "transcription (unverified)",
        "approved",
        "importing",
        "pending draft",
        "PENDING RAW DRAFT",
    ):
        assert text in prompt
    assert other["id"] not in prompt and "OTHER CASE SECRET" not in prompt
    assert response["coverage"]["uploads"] == 2
    assert f"upload/{second['id']}" in response["sources"]
    assert before == {
        str(path): path.read_bytes() for path in store.root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("variant", ["missing", "denied", "mismatch"])
async def test_authorization_before_collection_and_ai(variant: str) -> None:
    service, reader, ai = fixture_service()
    if variant == "denied":
        reader.fail.add("Patient")
    elif variant == "mismatch":
        reader.patient["id"] = "other"
    with pytest.raises(WebError):
        await service.send_assistant(
            {
                "role": "pacient",
                "text": "Q",
                "caseId": "absent" if variant == "missing" else "synthetic-1",
            }
        )
    assert len(reader.requests) == 1 and not ai.requests


async def test_foreign_search_resource_never_enters_prompt() -> None:
    service, reader, ai = fixture_service()
    reader.responses["Procedure"] = bundle(
        [
            {
                "resourceType": "Procedure",
                "id": "foreign",
                "subject": {"reference": "Patient/other"},
                "note": [{"text": "FOREIGN SECRET"}],
            }
        ]
    )
    with pytest.raises(WebError):
        await service.send_assistant({"role": "pacient", "text": "Q", "caseId": "synthetic-1"})
    assert not ai.requests


async def test_read_only_types_do_not_widen_writes(tmp_path: Path) -> None:
    app = BackendApp(tmp_path / "uds", fresh_tokens())
    await app.start()
    try:
        resource = {"resourceType": "MedicationRequest", "id": "m"}
        with pytest.raises(ContractError):
            app.store.fhir_write(resource)
    finally:
        await app.close()


async def test_json_escaped_prompt_fits_ipc_and_provider() -> None:
    service, reader, ai = fixture_service()
    reader.patient["extension"] = [{"valueString": '\\"\x01' * 50000}]
    await service.send_assistant({"role": "pacient", "text": "Q", "caseId": "synthetic-1"})
    request = ai.requests[0]
    assert len(canonical({"envelope": request.to_dict()})) < 4_194_304
    provider = DirectHttpTransport(
        DirectProviderConfig(
            "https://provider.invalid/v1", "model", "api-key", "key", allow_remote=True
        )
    )
    try:
        assert len(provider._request_body(request.payload["prompt"], None, "unused")) < 4_194_304
    finally:
        await provider.aclose()
