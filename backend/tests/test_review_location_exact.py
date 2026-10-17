from __future__ import annotations

from typing import Any

import pytest

from rakathon_backend.b2.iris.newreview import check_transaction_response
from rakathon_backend.common.errors import ContractError


def _body(locations: list[str | None]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for location in locations:
        response: dict[str, Any] = {"status": "201 Created"}
        if location is not None:
            response["location"] = location
        entries.append({"response": response})
    return {"resourceType": "Bundle", "type": "transaction-response", "entry": entries}


def test_relative_location_accepted() -> None:
    body = _body(["Observation/o1"])
    assert check_transaction_response(body, [("Observation", "o1")]) == body


def test_history_leading_slash_and_absolute_accepted() -> None:
    targets = [("Observation", "o1")]
    good = [
        "Observation/o1/_history/1",
        "/Observation/o1",
        "/Observation/o1/_history/2",
        "http://127.0.0.1:8765/fhir/r4/Observation/o1",
        "http://127.0.0.1:8765/fhir/r4/Observation/o1/_history/3",
        "https://iris.racek.xyz/fhir/r4/Observation/o1/_history/7",
    ]
    for location in good:
        assert check_transaction_response(_body([location]), targets) is not None


def test_missing_location_stays_optional() -> None:
    body = _body([None])
    assert check_transaction_response(body, [("Observation", "o1")]) == body


def test_prefix_collision_rejected() -> None:
    targets = [("Observation", "o1")]
    for location in ("Observation/o1-evil", "Observation/o1evil", "Observation/o12"):
        with pytest.raises(ContractError):
            check_transaction_response(_body([location]), targets)


def test_wrong_type_id_or_history_shape_rejected() -> None:
    targets = [("Observation", "o1")]
    bad = [
        "Patient/o1",
        "Observation/other",
        "Observation/o1/_history",
        "Observation/o1/_history/",
        "Observation/o1/_history/1/extra",
        "Observation/o1/history/1",
    ]
    for location in bad:
        with pytest.raises(ContractError):
            check_transaction_response(_body([location]), targets)


def test_malformed_or_unsafe_location_rejected() -> None:
    targets = [("Observation", "o1")]
    bad = [
        "",
        "   ",
        "Observation",
        "o1",
        "Observation//o1",
        "Observation/o1?x=1",
        "Observation/o1#frag",
        "Observation/o 1",
        "Observation\\o1",
        "Observation/../o1",
        "../Observation/o1",
        "Observation%2Fo1",
        "ftp://host/Observation/o1",
        "https://host/Observation/o1?x=1",
        "javascript:Observation/o1",
    ]
    for location in bad:
        with pytest.raises(ContractError):
            check_transaction_response(_body([location]), targets)


def test_multi_entry_uses_positional_targets() -> None:
    targets = [("Observation", "o1"), ("Observation", "o2")]
    good = _body(["Observation/o1/_history/1", "Observation/o2"])
    assert check_transaction_response(good, targets) == good
    with pytest.raises(ContractError):
        check_transaction_response(_body(["Observation/o1", "Observation/o1-evil"]), targets)
    with pytest.raises(ContractError):
        check_transaction_response(_body(["Observation/o2", "Observation/o2"]), targets)
