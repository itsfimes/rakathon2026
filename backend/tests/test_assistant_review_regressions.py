from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_fhir_pagination import BASE, adapter, observation, page
from test_web_assistant import fixture_service
from test_web_service import bundle

from rakathon_backend.b2.iris.fhir import MAX_BODY
from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.fhir import PATIENT_CONTEXT_TYPES
from rakathon_backend.converter.model_draft import build_model_draft
from rakathon_backend.uploads import store_read
from rakathon_backend.uploads.crypto import generate_key_file, open_sealed
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.web import patient_context
from rakathon_backend.web.assistant import DEADLINE, validate_request
from rakathon_backend.web.assistant_context import canonical
from rakathon_backend.web.auth_bridge import AI_TIMEOUT
from rakathon_backend.web.contracts import WebError
from rakathon_backend.web.patient_context import collect_patient_context
from rakathon_backend.web.patient_uploads import collect_uploads
from rakathon_backend.web.service import WebService


@pytest.mark.parametrize("case_id", [".", "..", "...", "-", "--", ".-."])
def test_non_alphanumeric_case_ids_rejected_before_http(case_id: str) -> None:
    with pytest.raises(WebError) as web_failure:
        validate_request({"role": "lekar", "text": "Q", "caseId": case_id})
    assert web_failure.value.status == 400
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"resourceType": "Patient", "id": case_id})

    with pytest.raises(ContractError) as failure:
        adapter(respond).read("Patient", case_id)
    assert failure.value.code == "bad_payload"
    assert not calls


@pytest.mark.parametrize(
    "next_link",
    [
        f"{BASE}/Patient?cursor=2",
        "/fhir/r4/Observation/$everything?cursor=2",
        "/fhir/r4/Observation/other?cursor=2",
        "/fhir/r4?cursor=2",
        "?patient=Patient/other",
        "?subject=Patient/other",
        "?patient=",
        "?_id=other",
        "?patient=Patient/p&patient=Patient/other",
        "?patient:identifier=other",
    ],
)
def test_next_link_cannot_change_search_scope_before_get(next_link: str) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=page([observation(0)], next_link))

    with pytest.raises(ContractError) as failure:
        adapter(respond).search("Observation", {"patient": "Patient/p"})
    assert failure.value.code == "unsafe_paging_link"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "next_link",
    [
        "?opaque=a%2Fb%2B%3D&cursor=x+y",
        "?patient=Patient/p&cursor=2",
        "?subject=Patient/p&cursor=2",
        "?_id=obs-0&cursor=2",
    ],
)
def test_next_link_preserves_matching_explicit_filters_and_opaque_cursors(next_link: str) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json=page(
                [observation(0)] if len(calls) == 1 else [], next_link if len(calls) == 1 else None
            ),
        )

    assert (
        len(adapter(respond).search("Observation", {"patient": "Patient/p", "_id": "obs-0"})) == 1
    )
    assert len(calls) == 2


async def test_oversized_patient_read_maps_to_context_413() -> None:
    fhir = adapter(lambda request: httpx.Response(200, content=b" " * (MAX_BODY + 1)))
    with pytest.raises(ContractError) as failure:
        fhir.read("Patient", "p")
    assert failure.value.code == "resource_limit"

    async def read(payload: dict[str, Any]) -> dict[str, Any]:
        found = fhir.read("Patient", "p")
        assert found is not None
        return bundle([found])

    with pytest.raises(WebError) as web_failure:
        await collect_patient_context(read, "p")
    assert (web_failure.value.status, web_failure.value.code) == (413, "context_too_large")


async def test_compartment_collection_is_bounded_concurrent_and_keeps_provider_budget() -> None:
    active = peak = 0
    collected = []

    async def read(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal active, peak
        if payload["resourceType"] == "Patient":
            return bundle([{"resourceType": "Patient", "id": "p"}])
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.001)
            collected.append(payload["resourceType"])
            return bundle([])
        finally:
            active -= 1

    context = await collect_patient_context(read, "p")
    assert peak == patient_context.COLLECTION_CONCURRENCY == 5
    assert active == 0 and set(collected) == set(PATIENT_CONTEXT_TYPES)
    assert len(context["manifest"]["types"]) == 21
    assert patient_context.COLLECTION_DEADLINE + 60 < DEADLINE < AI_TIMEOUT < 90


async def test_collection_deadline_cancels_all_pending_searches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(patient_context, "COLLECTION_DEADLINE", 0.02)
    active = 0

    async def read(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal active
        if payload["resourceType"] == "Patient":
            return bundle([{"resourceType": "Patient", "id": "p"}])
        active += 1
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1
        return bundle([])

    with pytest.raises(WebError) as failure:
        await collect_patient_context(read, "p")
    assert failure.value.status == 503 and active == 0


async def test_upload_without_readable_artifacts_is_partial(tmp_path: Path) -> None:
    store = UploadStore(tmp_path / "store", generate_key_file(tmp_path / "key"))
    store.enqueue("owner", "synthetic-1", "unreadable.pdf", b"pdf")
    _, reader, ai = fixture_service()
    response = (
        await WebService(reader, ai, uploads=store).send_assistant(
            {"role": "lekar", "text": "Q", "caseId": "synthetic-1"}
        )
    )[1]
    assert response["coverage"]["status"] == "partial"
    assert response["coverage"]["uploadsWithUnavailableArtifacts"] == 1
    assert "no readable artifacts" in ai.requests[0].payload["prompt"]


def test_large_encrypted_blob_rejected_before_decryption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = UploadStore(tmp_path / "store", generate_key_file(tmp_path / "key"))
    job = store.enqueue("owner", "p", "large.txt", b"file")
    store.write_result_blob(job["id"], "transcription", b"x" * 100_000)
    calls = []
    original = open_sealed

    def decrypt_blob(*args: Any) -> bytes:
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(store_read, "open_sealed", decrypt_blob)
    with pytest.raises(WebError) as failure:
        collect_uploads(store, "p", 2000)
    assert failure.value.code == "context_too_large" and not calls


async def test_incremental_upload_aggregate_budget_stops_before_later_jobs_and_ai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASSISTANT_MAX_CONTEXT_BYTES", "250000")
    store = UploadStore(tmp_path / "store", generate_key_file(tmp_path / "key"))
    jobs = [store.enqueue(f"owner-{i}", "synthetic-1", f"{i}.txt", b"file") for i in range(3)]
    for job in jobs:
        store.write_result_blob(
            job["id"],
            "model-draft",
            canonical(build_model_draft("x" * 100_000, job["sha256"], "test", "test")),
        )
    calls = []
    original = store.read_result_blob

    def read_blob(job_id: str, name: str, *, max_bytes: int | None = None) -> bytes | None:
        calls.append(job_id)
        return original(job_id, name, max_bytes=max_bytes)

    monkeypatch.setattr(store, "read_result_blob", read_blob)
    _, reader, ai = fixture_service()
    with pytest.raises(WebError) as failure:
        await WebService(reader, ai, uploads=store).send_assistant(
            {"role": "lekar", "text": "Q", "caseId": "synthetic-1"}
        )
    assert failure.value.code == "context_too_large" and not ai.requests
    assert jobs[2]["id"] not in calls


async def test_blocking_upload_read_does_not_block_loop_or_collection_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = UploadStore(tmp_path / "store", generate_key_file(tmp_path / "key"))
    store.enqueue("owner", "synthetic-1", "file.txt", b"file")
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def read_blob(job_id: str, name: str, *, max_bytes: int | None = None) -> bytes | None:
        calls.append(name)
        entered.set()
        release.wait(2)
        exited.set()
        return None

    monkeypatch.setattr(store, "read_result_blob", read_blob)
    monkeypatch.setattr(patient_context, "COLLECTION_DEADLINE", 0.1)
    _, reader, ai = fixture_service()
    task = asyncio.create_task(
        WebService(reader, ai, uploads=store).send_assistant(
            {"role": "lekar", "text": "Q", "caseId": "synthetic-1"}
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        with pytest.raises(WebError) as failure:
            await asyncio.wait_for(task, 0.5)
        assert failure.value.status == 503 and not ai.requests
    finally:
        release.set()
        assert await asyncio.to_thread(exited.wait, 1)
    assert calls == ["transcription"]
