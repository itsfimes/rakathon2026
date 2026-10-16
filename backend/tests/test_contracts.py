from typing import Any

import pytest

from rakathon_backend.common.contracts import DataKind, Envelope, Health
from rakathon_backend.common.errors import ContractError


def _base() -> dict[str, Any]:
    return {
        "version": 1,
        "requestId": "r-1",
        "correlationId": "c-1",
        "source": "b4",
        "target": "b6",
        "action": "authorize",
        "dataKind": "metadata",
        "payload": {"userId": "viewer", "action": "tasks.read"},
    }


def test_roundtrip_wire_keys() -> None:
    env = Envelope.from_dict(_base())
    wire = env.to_dict()
    assert wire["requestId"] == "r-1"
    assert wire["correlationId"] == "c-1"
    assert "userId" not in wire
    again = Envelope.from_dict(wire)
    assert again == env


def test_user_id_wire_key() -> None:
    raw = _base() | {"userId": "clinician"}
    env = Envelope.from_dict(raw)
    assert env.user_id == "clinician"
    assert env.to_dict()["userId"] == "clinician"


def test_reject_unexpected_keys() -> None:
    raw = _base() | {"role": "admin"}
    with pytest.raises(ContractError):
        Envelope.from_dict(raw)


def test_reject_bool_version() -> None:
    raw = _base() | {"version": True}
    with pytest.raises(ContractError):
        Envelope.from_dict(raw)


def test_reject_bad_version_and_kind() -> None:
    with pytest.raises(ContractError):
        Envelope.from_dict(_base() | {"version": 2})
    with pytest.raises(ContractError):
        Envelope.from_dict(_base() | {"dataKind": "fhir2"})


def test_reject_non_object_payload() -> None:
    with pytest.raises(ContractError):
        Envelope.from_dict(_base() | {"payload": ["x"]})


def test_reject_empty_and_missing() -> None:
    with pytest.raises(ContractError):
        Envelope.from_dict(_base() | {"source": ""})
    raw = _base()
    del raw["action"]
    with pytest.raises(ContractError):
        Envelope.from_dict(raw)


def test_reply_preserves_ids() -> None:
    env = Envelope.from_dict(_base())
    reply = env.reply(
        source="b6", action="authorize", payload={"allowed": True}, data_kind=DataKind.METADATA
    )
    assert reply.request_id == "r-1"
    assert reply.correlation_id == "c-1"
    assert reply.source == "b6"
    assert reply.target == "b4"


def test_error_reply_is_safe() -> None:
    env = Envelope.from_dict(_base())
    reply = env.error_reply(source="b6", code="deny", message="no")
    assert reply.action == "error"
    assert set(reply.payload) == {"code", "message"}


def test_health_values() -> None:
    assert {h.value for h in Health} == {"HEALTHY", "DEGRADED", "DOWN"}
