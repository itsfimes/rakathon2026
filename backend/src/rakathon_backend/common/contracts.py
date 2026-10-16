from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from rakathon_backend.common.errors import ContractError


class DataKind(str, Enum):
    FHIR = "fhir"
    PROPRIETARY = "proprietary"
    METADATA = "metadata"


class Health(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"


ENVELOPE_VERSION = 1
ERROR_ACTION = "error"
HEALTH_ACTION = "health"

_MAX_ID_LEN = 128
_MAX_NAME_LEN = 64

_WIRE_KEYS = frozenset(
    {
        "version",
        "requestId",
        "correlationId",
        "source",
        "target",
        "action",
        "dataKind",
        "payload",
        "userId",
    }
)


def _check_text(value: Any, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ContractError(code="bad_type", message=f"{label} must be a string")
    if not value or not value.strip():
        raise ContractError(code="empty_field", message=f"{label} must be nonempty")
    if len(value) > limit:
        raise ContractError(code="too_long", message=f"{label} exceeds length limit")
    return value


def _check_version(value: Any) -> int:
    if type(value) is not int:
        raise ContractError(code="bad_version", message="version must be an integer")
    if value != ENVELOPE_VERSION:
        raise ContractError(code="bad_version", message="unsupported envelope version")
    return value


def _check_kind(value: Any) -> DataKind:
    if not isinstance(value, str):
        raise ContractError(code="bad_kind", message="dataKind must be a string")
    try:
        return DataKind(value)
    except ValueError as exc:
        raise ContractError(code="bad_kind", message="unsupported data kind") from exc


def _check_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(code="bad_payload", message="payload must be a JSON object")
    return dict(value)


@dataclass(frozen=True, slots=True)
class Envelope:
    request_id: str
    correlation_id: str
    source: str
    target: str
    action: str
    data_kind: DataKind
    payload: dict[str, Any] = field(default_factory=dict)
    user_id: str | None = None
    version: int = ENVELOPE_VERSION

    def to_dict(self) -> dict[str, Any]:
        wire: dict[str, Any] = {
            "version": self.version,
            "requestId": self.request_id,
            "correlationId": self.correlation_id,
            "source": self.source,
            "target": self.target,
            "action": self.action,
            "dataKind": self.data_kind.value,
            "payload": dict(self.payload),
        }
        if self.user_id is not None:
            wire["userId"] = self.user_id
        return wire

    @staticmethod
    def from_dict(raw: Any) -> Envelope:
        if not isinstance(raw, dict):
            raise ContractError(code="bad_envelope", message="envelope must be a JSON object")
        unknown = set(raw) - _WIRE_KEYS
        if unknown:
            raise ContractError(code="unexpected_keys", message="envelope has unexpected keys")
        for key in (
            "version",
            "requestId",
            "correlationId",
            "source",
            "target",
            "action",
            "dataKind",
            "payload",
        ):
            if key not in raw:
                raise ContractError(code="missing_key", message=f"envelope missing {key}")
        version = _check_version(raw["version"])
        request_id = _check_text(raw["requestId"], "requestId", _MAX_ID_LEN)
        correlation_id = _check_text(raw["correlationId"], "correlationId", _MAX_ID_LEN)
        source = _check_text(raw["source"], "source", _MAX_NAME_LEN)
        target = _check_text(raw["target"], "target", _MAX_NAME_LEN)
        action = _check_text(raw["action"], "action", _MAX_NAME_LEN)
        data_kind = _check_kind(raw["dataKind"])
        payload = _check_payload(raw["payload"])
        user_id: str | None = None
        if "userId" in raw and raw["userId"] is not None:
            user_id = _check_text(raw["userId"], "userId", _MAX_ID_LEN)
        return Envelope(
            request_id=request_id,
            correlation_id=correlation_id,
            source=source,
            target=target,
            action=action,
            data_kind=data_kind,
            payload=payload,
            user_id=user_id,
            version=version,
        )

    def reply(
        self,
        *,
        source: str,
        action: str,
        payload: dict[str, Any],
        data_kind: DataKind,
    ) -> Envelope:
        return Envelope(
            request_id=self.request_id,
            correlation_id=self.correlation_id,
            source=_check_text(source, "source", _MAX_NAME_LEN),
            target=self.source,
            action=_check_text(action, "action", _MAX_NAME_LEN),
            data_kind=data_kind,
            payload=_check_payload(payload),
            user_id=self.user_id,
            version=ENVELOPE_VERSION,
        )

    def error_reply(self, *, source: str, code: str, message: str) -> Envelope:
        safe_code = code if isinstance(code, str) and code else "internal_error"
        safe_message = message if isinstance(message, str) and message else "request failed"
        return Envelope(
            request_id=self.request_id,
            correlation_id=self.correlation_id,
            source=_check_text(source, "source", _MAX_NAME_LEN),
            target=self.source,
            action=ERROR_ACTION,
            data_kind=DataKind.METADATA,
            payload={"code": safe_code, "message": safe_message},
            user_id=self.user_id,
            version=ENVELOPE_VERSION,
        )
