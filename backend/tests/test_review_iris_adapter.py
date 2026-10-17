from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from rakathon_backend.b2.iris.config import IrisFhirConfig
from rakathon_backend.b2.iris.fhir import DirectFhirAdapter
from rakathon_backend.b2.iris.fhir_only import FhirOnlyStorage
from rakathon_backend.common.errors import ContractError
from rakathon_backend.uploads.review_validation import prepare_review_import

BASE = "http://127.0.0.1:8765/fhir/r4"
PATIENT_ID = "target-1"
SOURCE = "urn:sha256:" + "a" * 64
APPROVAL = "approval-1"
ALIAS = "model-p9"
Handler = Callable[[httpx.Request], httpx.Response]


def _candidate(entries: int = 1) -> dict[str, Any]:
    items: list[dict[str, Any]] = [
        {
            "resource": {"resourceType": "Patient", "id": ALIAS},
            "request": {"method": "PUT", "url": "Patient/" + ALIAS},
        }
    ]
    for num in range(entries):
        rid = "o" + str(num + 1)
        items.append(
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": rid,
                    "status": "final",
                    "code": {"text": "GLU"},
                    "subject": {"reference": "Patient/" + ALIAS},
                },
                "request": {"method": "PUT", "url": "Observation/" + rid},
            }
        )
    return {"resourceType": "Bundle", "type": "transaction", "entry": items}


def _valid_bundle(entries: int = 1) -> dict[str, Any]:
    prepared = prepare_review_import(
        json.dumps(_candidate(entries)),
        patient_id=PATIENT_ID,
        source_urn=SOURCE,
        approval_id=APPROVAL,
        patient_confirmed=True,
    )
    return dict(prepared["bundle"])


def _targets(bundle: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    raw = bundle.get("entry")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("resource"), dict):
                res = item["resource"]
                out.append((str(res.get("resourceType")), str(res.get("id"))))
    return out


def _outcome(severity: str, code: str) -> dict[str, Any]:
    return {"resourceType": "OperationOutcome", "issue": [{"severity": severity, "code": code}]}


def _tx_response(bundle: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for rtype, rid in _targets(bundle):
        entries.append(
            {"response": {"status": "201 Created", "location": rtype + "/" + rid + "/_history/1"}}
        )
    return {"resourceType": "Bundle", "type": "transaction-response", "entry": entries}


def _adapter(handler: Handler, calls: list[httpx.Request]) -> DirectFhirAdapter:
    def track(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    client = httpx.Client(
        transport=httpx.MockTransport(track), base_url=BASE, trust_env=False, follow_redirects=False
    )
    return DirectFhirAdapter(IrisFhirConfig(base_url=BASE, username="u", password="p"), client)


def _is_validate(request: httpx.Request) -> bool:
    return request.method == "POST" and "$validate" in request.url.path


def _is_tx(request: httpx.Request) -> bool:
    return request.method == "POST" and "$validate" not in request.url.path


def _patient_hit(request: httpx.Request) -> bool:
    return request.method == "GET" and request.url.path.endswith("/Patient/" + PATIENT_ID)


def _flow_handler(bundle: dict[str, Any], validate_body: Any, tx_body: Any) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if _patient_hit(request):
            return httpx.Response(200, json={"resourceType": "Patient", "id": PATIENT_ID})
        if request.method == "GET":
            return httpx.Response(404, json={})
        if _is_validate(request):
            return httpx.Response(200, json=validate_body)
        if _is_tx(request):
            return httpx.Response(200, json=tx_body)
        return httpx.Response(404, json={})

    return handler


def test_invalid_bundle_makes_no_posts() -> None:
    calls: list[httpx.Request] = []
    adapter = _adapter(lambda request: httpx.Response(200, json={}), calls)
    with pytest.raises(ContractError):
        adapter.review_transaction({"resourceType": "Bundle", "type": "transaction"}, PATIENT_ID)
    with pytest.raises(ContractError):
        adapter.review_transaction(_candidate(1), PATIENT_ID)
    assert calls == []


def test_validate_error_blocks_transaction() -> None:
    bundle = _valid_bundle()
    calls: list[httpx.Request] = []
    adapter = _adapter(_flow_handler(bundle, _outcome("error", "invalid"), {}), calls)
    with pytest.raises(ContractError) as excinfo:
        adapter.review_transaction(bundle, PATIENT_ID)
    assert excinfo.value.code == "validation_failed"
    assert sum(1 for item in calls if _is_validate(item)) == len(_targets(bundle))
    assert sum(1 for item in calls if _is_tx(item)) == 0


def test_validate_not_supported_blocks_transaction() -> None:
    bundle = _valid_bundle()
    calls: list[httpx.Request] = []
    adapter = _adapter(_flow_handler(bundle, _outcome("warning", "not-supported"), {}), calls)
    with pytest.raises(ContractError):
        adapter.review_transaction(bundle, PATIENT_ID)
    assert sum(1 for item in calls if _is_tx(item)) == 0


def test_validate_missing_blocks_transaction() -> None:
    bundle = _valid_bundle()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if _patient_hit(request):
            return httpx.Response(200, json={"resourceType": "Patient", "id": PATIENT_ID})
        if request.method == "GET":
            return httpx.Response(404, json={})
        return httpx.Response(404, json={})

    adapter = _adapter(handler, calls)
    with pytest.raises(ContractError):
        adapter.review_transaction(bundle, PATIENT_ID)
    assert sum(1 for item in calls if _is_tx(item)) == 0


def test_valid_flow_posts_single_atomic_transaction() -> None:
    bundle = _valid_bundle()
    calls: list[httpx.Request] = []
    adapter = _adapter(
        _flow_handler(bundle, _outcome("information", "informational"), _tx_response(bundle)), calls
    )
    result = adapter.review_transaction(bundle, PATIENT_ID)
    assert result.get("type") == "transaction-response"
    assert sum(1 for item in calls if _is_tx(item)) == 1
    assert sum(1 for item in calls if _is_validate(item)) == len(_targets(bundle))
    for item in bundle["entry"]:
        assert item["resource"]["resourceType"] != "Patient"
    assert all("/Patient/" not in item.url.path or item.method != "PUT" for item in calls)


def test_missing_patient_blocks_writes() -> None:
    bundle = _valid_bundle()
    calls: list[httpx.Request] = []
    adapter = _adapter(lambda request: httpx.Response(404, json={}), calls)
    with pytest.raises(ContractError) as excinfo:
        adapter.review_transaction(bundle, PATIENT_ID)
    assert excinfo.value.code == "missing_patient"
    assert sum(1 for item in calls if item.method == "POST") == 0


def test_foreign_subject_and_ref_blocked() -> None:
    bundle = _valid_bundle()
    calls: list[httpx.Request] = []
    adapter = _adapter(lambda request: httpx.Response(200, json={}), calls)
    foreign = copy.deepcopy(bundle)
    foreign["entry"][0]["resource"]["subject"] = {"reference": "Patient/other-case"}
    with pytest.raises(ContractError):
        adapter.review_transaction(foreign, PATIENT_ID)
    dangling = copy.deepcopy(bundle)
    dangling["entry"][0]["resource"]["result"] = [{"reference": "Observation/elsewhere"}]
    with pytest.raises(ContractError):
        adapter.review_transaction(dangling, PATIENT_ID)
    assert sum(1 for item in calls if item.method == "POST") == 0


def test_matching_readback_returns_without_posts() -> None:
    bundle = _valid_bundle()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if _patient_hit(request):
            return httpx.Response(200, json={"resourceType": "Patient", "id": PATIENT_ID})
        if request.method == "GET":
            stored = copy.deepcopy(bundle["entry"][0]["resource"])
            meta = dict(stored.get("meta", {}))
            meta["versionId"] = "1"
            meta["lastUpdated"] = "2026-01-01T00:00:00Z"
            stored["meta"] = meta
            return httpx.Response(200, json=stored)
        return httpx.Response(200, json=_outcome("information", "informational"))

    adapter = _adapter(handler, calls)
    result = adapter.review_transaction(bundle, PATIENT_ID)
    assert result.get("alreadyApplied") is True
    assert result.get("type") == "transaction-response"
    assert sum(1 for item in calls if item.method == "POST") == 0


def test_collision_and_partial_existing_conflict() -> None:
    bundle = _valid_bundle()
    calls: list[httpx.Request] = []

    def clash(request: httpx.Request) -> httpx.Response:
        if _patient_hit(request):
            return httpx.Response(200, json={"resourceType": "Patient", "id": PATIENT_ID})
        if request.method == "GET":
            stored = copy.deepcopy(bundle["entry"][0]["resource"])
            stored["status"] = "preliminary"
            return httpx.Response(200, json=stored)
        return httpx.Response(200, json=_outcome("information", "informational"))

    with pytest.raises(ContractError) as excinfo:
        _adapter(clash, calls).review_transaction(bundle, PATIENT_ID)
    assert excinfo.value.code == "import_conflict"
    assert sum(1 for item in calls if item.method == "POST") == 0
    two = _valid_bundle(2)
    wanted = _targets(two)
    second_calls: list[httpx.Request] = []

    def partial(request: httpx.Request) -> httpx.Response:
        if _patient_hit(request):
            return httpx.Response(200, json={"resourceType": "Patient", "id": PATIENT_ID})
        if request.method == "GET" and request.url.path.endswith("/" + wanted[0][1]):
            for item in two["entry"]:
                if item["resource"]["id"] == wanted[0][1]:
                    return httpx.Response(200, json=copy.deepcopy(item["resource"]))
        if request.method == "GET":
            return httpx.Response(404, json={})
        return httpx.Response(200, json=_outcome("information", "informational"))

    with pytest.raises(ContractError) as excinfo2:
        _adapter(partial, second_calls).review_transaction(two, PATIENT_ID)
    assert excinfo2.value.code == "import_conflict"
    assert sum(1 for item in second_calls if item.method == "POST") == 0


def test_malformed_transaction_response_fails_closed() -> None:
    bundle = _valid_bundle()
    bad_bodies: list[dict[str, Any]] = [
        {"resourceType": "Bundle", "type": "searchset", "entry": []},
        {"resourceType": "Bundle", "type": "transaction-response", "entry": []},
        {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "entry": [{"response": {"status": "400 Bad Request"}}],
        },
        {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "entry": [
                {
                    "response": {"status": "201 Created"},
                    "resource": _outcome("error", "invalid"),
                }
            ],
        },
    ]
    for index, bad in enumerate(bad_bodies):
        calls: list[httpx.Request] = []
        adapter = _adapter(
            _flow_handler(bundle, _outcome("information", "informational"), bad), calls
        )
        with pytest.raises(ContractError):
            adapter.review_transaction(bundle, PATIENT_ID)
        assert sum(1 for item in calls if _is_tx(item)) == 1 + index - index


def test_storage_delegates_review_transaction() -> None:
    bundle = _valid_bundle()
    calls: list[httpx.Request] = []
    inner = _adapter(
        _flow_handler(bundle, _outcome("information", "informational"), _tx_response(bundle)), calls
    )
    store = FhirOnlyStorage(inner)
    result = store.fhir_review_transaction(bundle, PATIENT_ID)
    assert result.get("type") == "transaction-response"
    assert sum(1 for item in calls if _is_tx(item)) == 1
