from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import httpx
import pytest
from direct_fixtures import outcome, provider_response, transaction

from rakathon_backend.b1.outcome import TAG_SYSTEM, prepare_import
from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.b5.direct import DirectAdapter
from rakathon_backend.b5.direct_http import DirectHttpTransport, DirectProviderConfig
from rakathon_backend.common.contracts import DataKind
from rakathon_backend.common.errors import ContractError, TransportError
from rakathon_backend.common.rpc import new_envelope
from rakathon_backend.runtime.application import BackendApp, fresh_tokens
from rakathon_backend.runtime.ingest import _run_ingest


class RecordingStore(MemoryStorage):
    def __init__(self) -> None:
        super().__init__()
        self.transactions: list[dict[str, Any]] = []
        self.fail = False

    def fhir_transaction(self, bundle: dict[str, Any]) -> dict[str, Any]:
        self.transactions.append(copy.deepcopy(bundle))
        if self.fail:
            raise OSError("synthetic storage failure")
        return super().fhir_transaction(bundle)


def app_for(tmp_path: Path, output: dict[str, Any]) -> tuple[BackendApp, RecordingStore]:
    config = DirectProviderConfig(
        base_url="https://synthetic.invalid/v1",
        model="synthetic",
        auth_scheme="bearer",
        api_key="synthetic-key",
        allow_remote=True,
    )
    adapter = DirectAdapter(
        DirectHttpTransport(
            config, transport=httpx.MockTransport(lambda req: provider_response(output))
        )
    )
    store = RecordingStore()
    return BackendApp(
        tmp_path / "uds", fresh_tokens(), store=store, ai_adapter=adapter, ai_mode="direct"
    ), store


@pytest.mark.parametrize(
    "status,expected", [("complete", 2), ("incomplete", 2), ("manual-review", 0)]
)
async def test_actual_b1_b4_b5_b2_partial_outcomes(
    tmp_path: Path, status: str, expected: int
) -> None:
    app, store = app_for(tmp_path, outcome(status))
    await app.start()
    try:
        summary = await _run_ingest(
            app,
            b"Synthetic explicitly associated source",
            "text/plain",
            "admin",
            "direct",
            "synthetic-1",
        )
        assert summary["status"] == status and summary["storedCount"] == expected
        assert summary["needsReview"] is (status != "complete")
        assert summary["writeEligible"] is (status != "manual-review")
        assert len(store.transactions) == (1 if expected else 0)
        assert len(store.fhir) == expected
        if expected:
            resources = [entry["resource"] for entry in store.transactions[0]["entry"]]
            assert resources[0]["active"] is False
            assert resources[1]["valueQuantity"]["value"] == 0
            assert resources[1]["effectiveDateTime"] == "2026-01"
            for resource in resources:
                assert resource["meta"]["tag"] == [{"system": TAG_SYSTEM, "code": status}]
                assert resource["meta"]["source"] == summary["sourceUrn"]
            assert resources[1]["status"] == "final"
            assert bool(summary["issues"]) is (status == "incomplete")
    finally:
        await app.close()


async def test_no_trusted_patient_context_means_no_writes(tmp_path: Path) -> None:
    app, store = app_for(tmp_path, outcome())
    await app.start()
    try:
        summary = await _run_ingest(app, b"Synthetic source", "text/plain", "admin", "direct")
        assert summary["status"] == "manual-review" and summary["storedCount"] == 0
        assert not store.transactions and not store.fhir
    finally:
        await app.close()


@pytest.mark.parametrize(
    "mutation",
    [
        "status",
        "required-code",
        "date",
        "raw-boolean",
        "unknown-field",
        "subject",
        "dangling",
        "complete-issues",
        "incomplete-no-issues",
        "manual-with-bundle",
        "null-required",
        "legacy-flag",
    ],
)
async def test_invalid_provider_content_zero_store_calls(tmp_path: Path, mutation: str) -> None:
    output = outcome()
    observation = output["bundle"]["entry"][1]["resource"]
    if mutation == "status":
        observation["status"] = "custom-invalid-status"
    elif mutation == "required-code":
        del observation["code"]
    elif mutation == "date":
        observation["effectiveDateTime"] = "not-a-date"
    elif mutation == "raw-boolean":
        output["bundle"]["entry"][0]["resource"]["active"] = "false"
    elif mutation == "unknown-field":
        observation["unexpected"] = "invalid"
    elif mutation == "subject":
        observation["subject"]["reference"] = "Patient/other"
    elif mutation == "dangling":
        observation["derivedFrom"] = [{"reference": "Observation/missing"}]
    elif mutation == "complete-issues":
        output["issues"] = outcome("incomplete")["issues"]
    elif mutation == "incomplete-no-issues":
        output["status"] = "incomplete"
    elif mutation == "manual-with-bundle":
        output["status"] = "manual-review"
        output["issues"] = outcome("incomplete")["issues"]
    elif mutation == "null-required":
        observation["status"] = None
    elif mutation == "legacy-flag":
        output["manualReview"] = False
    app, store = app_for(tmp_path, output)
    await app.start()
    try:
        with pytest.raises((ContractError, TransportError, OSError)):
            await _run_ingest(
                app, b"Synthetic source", "text/plain", "admin", "direct", "synthetic-1"
            )
        assert not store.transactions and not store.fhir
    finally:
        await app.close()


async def test_existing_record_conflict_and_storage_failure_not_success(tmp_path: Path) -> None:
    app, store = app_for(tmp_path, outcome("incomplete"))
    await app.start()
    try:
        store.fhir[("Patient", "synthetic-1")] = {"resourceType": "Patient", "id": "synthetic-1"}
        with pytest.raises(TransportError):
            await _run_ingest(
                app, b"Synthetic source", "text/plain", "admin", "direct", "synthetic-1"
            )
        assert not store.transactions and len(store.fhir) == 1
        store.fhir.clear()
        store.fail = True
        with pytest.raises(TransportError):
            await _run_ingest(
                app, b"Synthetic source", "text/plain", "admin", "direct", "synthetic-1"
            )
        assert len(store.transactions) == 1 and not store.fhir
    finally:
        await app.close()


@pytest.mark.parametrize(
    "mutation", ["status", "date", "number", "subject", "envelope-entry", "nontransaction"]
)
async def test_alternate_b2_write_independent_gate(tmp_path: Path, mutation: str) -> None:
    app = BackendApp(tmp_path / "uds", fresh_tokens())
    payload = transaction()
    resource = payload["entry"][1]["resource"]
    if mutation == "status":
        resource["status"] = "custom-invalid"
    elif mutation == "date":
        resource["effectiveDateTime"] = "impossible"
    elif mutation == "number":
        resource["valueQuantity"]["value"] = "0"
    elif mutation == "subject":
        resource["subject"] = False
    elif mutation == "envelope-entry":
        payload["entry"][1]["resource"] = {
            "resourceType": "Bundle",
            "id": "nested",
            "type": "collection",
        }
    elif mutation == "nontransaction":
        payload["type"] = "collection"
    await app.start()
    try:
        client = app.frontend_client("admin")
        with pytest.raises((ContractError, TransportError)):
            await client.call(
                new_envelope(
                    source="frontend:admin",
                    target="b4",
                    action="fhir.write",
                    data_kind=DataKind.FHIR,
                    payload=payload,
                    user_id="admin",
                ),
                expect_source="b4",
            )
        assert isinstance(app.store, MemoryStorage) and not app.store.fhir
    finally:
        await app.close()


def test_tagged_output_revalidated_and_association_cannot_be_selected() -> None:
    with pytest.raises(ContractError):
        prepare_import(outcome(), "urn:sha256:" + "a" * 64, "other-patient")
