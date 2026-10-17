import pytest

from rakathon_backend.b6.permissions import (
    ACTIONS,
    Policy,
    check,
    load_matrix,
    make_authorize_handler,
)
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError


def test_matrix_loads_packaged() -> None:
    policy = load_matrix()
    assert policy.role_for("viewer") == "viewer"
    assert policy.role_for("nobody") is None


def test_expected_users_present() -> None:
    policy = load_matrix()
    for user in ("coordinator", "clinician", "viewer", "watchdog", "admin"):
        assert policy.role_for(user) is not None


def test_expected_actions_defined() -> None:
    for action in (
        "health",
        "ingest",
        "fhir.read",
        "fhir.write",
        "tasks.read",
        "tasks.write",
        "tasks.ack",
        "vector.anonymized.search",
        "vector.patient.search",
        "ai.translate",
        "ai.complete",
        "reminders.read",
        "watchdog.tick",
    ):
        assert action in ACTIONS


def test_deny_unknown_user_and_action() -> None:
    policy = load_matrix()
    assert check(policy, "ghost", "tasks.read").allowed is False
    assert check(policy, "viewer", "nope.action").allowed is False


def test_viewer_cannot_write() -> None:
    policy = load_matrix()
    decision = check(policy, "viewer", "tasks.write")
    assert decision.allowed is False
    assert decision.reason


def test_admin_can_write_patient_search() -> None:
    policy = load_matrix()
    assert check(policy, "admin", "vector.patient.search").allowed is True


@pytest.mark.parametrize("user", ["coordinator", "clinician", "viewer", "admin"])
def test_all_human_roles_can_ask_assistant(user: str) -> None:
    assert check(load_matrix(), user, "ai.ask").allowed is True


@pytest.mark.parametrize("user", ["coordinator", "clinician", "viewer"])
def test_human_assistant_permission_does_not_allow_direct_ai_or_fhir_writes(user: str) -> None:
    policy = load_matrix()
    assert check(policy, user, "ai.complete").allowed is False
    assert check(policy, user, "fhir.write").allowed is False


def test_service_principals_keep_narrow_assistant_permissions() -> None:
    policy = load_matrix()
    assert check(policy, "watchdog", "ai.ask").allowed is False
    assert policy.actions_for_role("web-assistant") == frozenset({"ai.complete"})


def test_check_is_pure_no_caller_role() -> None:
    policy = Policy(roles={"viewer": frozenset({"tasks.read"})}, users={"viewer": "viewer"})
    allowed = check(policy, "viewer", "tasks.write")
    assert allowed.allowed is False


async def test_authorize_handler_allows_known() -> None:
    policy = load_matrix()
    handler = make_authorize_handler(policy, service_name="b6", allowed_sources=frozenset({"b4"}))
    request = Envelope(
        request_id="r",
        correlation_id="c",
        source="b4",
        target="b6",
        action="authorize",
        data_kind=DataKind.METADATA,
        payload={"userId": "viewer", "action": "tasks.read"},
        user_id="viewer",
    )
    reply = await handler(request)
    assert reply.payload["allowed"] is True
    assert reply.request_id == "r"


async def test_authorize_handler_denies_unknown_user() -> None:
    policy = load_matrix()
    handler = make_authorize_handler(policy, service_name="b6", allowed_sources=frozenset({"b4"}))
    request = Envelope(
        request_id="r",
        correlation_id="c",
        source="b4",
        target="b6",
        action="authorize",
        data_kind=DataKind.METADATA,
        payload={"userId": "ghost", "action": "tasks.read"},
        user_id="ghost",
    )
    reply = await handler(request)
    assert reply.payload["allowed"] is False


async def test_authorize_handler_rejects_untrusted_source() -> None:
    policy = load_matrix()
    handler = make_authorize_handler(policy, service_name="b6", allowed_sources=frozenset({"b4"}))
    request = Envelope(
        request_id="r",
        correlation_id="c",
        source="b9",
        target="b6",
        action="authorize",
        data_kind=DataKind.METADATA,
        payload={"userId": "viewer", "action": "tasks.read"},
        user_id="viewer",
    )
    with pytest.raises(AuthError):
        await handler(request)


async def test_authorize_handler_binds_envelope_user() -> None:
    policy = load_matrix()
    handler = make_authorize_handler(policy, service_name="b6", allowed_sources=frozenset({"b4"}))

    def ask(payload_user: str, envelope_user: str | None) -> Envelope:
        return Envelope(
            request_id="r",
            correlation_id="c",
            source="b4",
            target="b6",
            action="authorize",
            data_kind=DataKind.METADATA,
            payload={"userId": payload_user, "action": "tasks.read"},
            user_id=envelope_user,
        )

    reply = await handler(ask("viewer", "viewer"))
    assert reply.payload["allowed"] is True
    with pytest.raises(AuthError):
        await handler(ask("viewer", "clinician"))
    with pytest.raises(ContractError):
        await handler(ask("viewer", None))
    with pytest.raises(ContractError):
        await handler(ask("", ""))
