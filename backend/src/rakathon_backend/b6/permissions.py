from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError, ContractError, TransportError

HEALTH = "health"
INGEST = "ingest"
FHIR_READ = "fhir.read"
FHIR_SEARCH = "fhir.search"
FHIR_WRITE = "fhir.write"
SCREENING_QUERY = "screening.query"
TASKS_READ = "tasks.read"
TASKS_WRITE = "tasks.write"
TASKS_ACK = "tasks.ack"
VECTOR_ANON_SEARCH = "vector.anonymized.search"
VECTOR_PATIENT_SEARCH = "vector.patient.search"
AI_TRANSLATE = "ai.translate"
AI_COMPLETE = "ai.complete"
AI_ASK = "ai.ask"
REMINDERS_READ = "reminders.read"
WATCHDOG_TICK = "watchdog.tick"
AUTHORIZE = "authorize"
DOCUMENT_UPLOAD = "document.upload"
DOCUMENT_APPROVE = "document.approve"

ACTIONS = frozenset(
    {
        HEALTH,
        INGEST,
        FHIR_READ,
        FHIR_WRITE,
        SCREENING_QUERY,
        TASKS_READ,
        TASKS_WRITE,
        TASKS_ACK,
        VECTOR_ANON_SEARCH,
        VECTOR_PATIENT_SEARCH,
        AI_TRANSLATE,
        AI_COMPLETE,
        AI_ASK,
        REMINDERS_READ,
        WATCHDOG_TICK,
        AUTHORIZE,
        DOCUMENT_UPLOAD,
        DOCUMENT_APPROVE,
    }
)

_HANDLER_ACTIONS = frozenset({AUTHORIZE})


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class Policy:
    roles: dict[str, frozenset[str]]
    users: dict[str, str]

    def role_for(self, user_id: str) -> str | None:
        return self.users.get(user_id)

    def actions_for_role(self, role: str) -> frozenset[str]:
        return self.roles.get(role, frozenset())


RoleResolver = Callable[[str], str | None]


def canonical_action(action: str) -> str:
    if action == FHIR_SEARCH:
        return FHIR_READ
    return action


def _resolve_role(policy: Policy, user_id: str, role_resolver: RoleResolver | None) -> str | None:
    if role_resolver is None:
        return policy.role_for(user_id)
    try:
        resolved = role_resolver(user_id)
    except (ContractError, AuthError, TransportError, OSError, ValueError):
        return None
    except (KeyError, RuntimeError, AttributeError, TypeError):
        return None
    if resolved is None:
        return None
    if not isinstance(resolved, str) or resolved not in policy.roles:
        return None
    if resolved == "watchdog" and user_id != "watchdog":
        return None
    return resolved


def check(
    policy: Policy, user_id: str, action: str, role_resolver: RoleResolver | None = None
) -> Decision:
    role = _resolve_role(policy, user_id, role_resolver)
    if role is None:
        return Decision(allowed=False, reason="unknown user")
    action = canonical_action(action)
    if action not in ACTIONS:
        return Decision(allowed=False, reason="unknown action")
    if action in policy.actions_for_role(role):
        return Decision(allowed=True, reason=f"role {role} permits {action}")
    return Decision(allowed=False, reason=f"role {role} denies {action}")


def load_matrix(path: Path | None = None) -> Policy:
    raw_text = path.read_text(encoding="utf-8") if path is not None else _packaged_text()
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ContractError(code="bad_matrix", message="matrix is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise ContractError(code="bad_matrix", message="matrix must be a JSON object")
    roles_raw = raw.get("roles")
    users_raw = raw.get("users")
    if not isinstance(roles_raw, dict) or not roles_raw:
        raise ContractError(code="bad_matrix", message="matrix roles invalid")
    if not isinstance(users_raw, dict) or not users_raw:
        raise ContractError(code="bad_matrix", message="matrix users invalid")
    roles: dict[str, frozenset[str]] = {}
    for role, actions in roles_raw.items():
        if not isinstance(role, str) or not role.strip():
            raise ContractError(code="bad_matrix", message="matrix role name invalid")
        if not isinstance(actions, list) or not actions:
            raise ContractError(code="bad_matrix", message=f"role {role} actions invalid")
        parsed: set[str] = set()
        for action in actions:
            if not isinstance(action, str) or action not in ACTIONS or action == AUTHORIZE:
                raise ContractError(code="bad_matrix", message=f"role {role} action invalid")
            parsed.add(action)
        roles[role] = frozenset(parsed)
    users: dict[str, str] = {}
    for user, role in users_raw.items():
        if not isinstance(user, str) or not user.strip():
            raise ContractError(code="bad_matrix", message="matrix user invalid")
        if not isinstance(role, str) or role not in roles:
            raise ContractError(code="bad_matrix", message=f"user {user} role invalid")
        users[user] = role
    return Policy(roles=roles, users=users)


def _packaged_text() -> str:
    return files("rakathon_backend.b6").joinpath("matrix.json").read_text(encoding="utf-8")


def privileged_users(policy: Policy) -> frozenset[str]:
    out: set[str] = set()
    for user, role in policy.users.items():
        if role in ("admin", "coordinator", "watchdog") and role in policy.roles:
            out.add(user)
    return frozenset(out)


def make_authorize_handler(
    policy: Policy,
    *,
    service_name: str,
    allowed_sources: frozenset[str],
    role_resolver: RoleResolver | None = None,
) -> Callable[[Envelope], Awaitable[Envelope]]:
    if not service_name or not service_name.strip():
        raise ValueError("service_name must be nonempty")
    if not allowed_sources:
        raise ValueError("allowed_sources must be nonempty")

    async def handler(request: Envelope) -> Envelope:
        if request.source not in allowed_sources:
            raise AuthError(code="auth_failed", message="source is not permitted")
        if request.action not in _HANDLER_ACTIONS:
            raise ContractError(code="bad_action", message="unsupported action")
        payload = request.payload
        user_id = payload.get("userId")
        action = payload.get("action")
        if not isinstance(user_id, str) or not user_id.strip():
            raise ContractError(code="bad_payload", message="userId must be a string")
        if not isinstance(action, str) or not action.strip():
            raise ContractError(code="bad_payload", message="action must be a string")
        envelope_user = request.user_id
        if not isinstance(envelope_user, str) or not envelope_user.strip():
            raise ContractError(code="bad_payload", message="userId must be a string")
        if envelope_user != user_id:
            raise AuthError(code="auth_failed", message="user mismatch")
        decision = check(policy, user_id, action, role_resolver)
        return request.reply(
            source=service_name,
            action=AUTHORIZE,
            payload={"allowed": decision.allowed, "reason": decision.reason},
            data_kind=DataKind.METADATA,
        )

    return handler
