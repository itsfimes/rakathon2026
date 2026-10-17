from __future__ import annotations

from typing import Any

from rakathon_backend.common.collection import checked_metadata


class ContractError(ValueError):
    def __init__(
        self,
        code: str = "contract_error",
        message: str = "invalid envelope",
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.metadata = checked_metadata(metadata or {})


class AuthError(PermissionError):
    def __init__(
        self,
        code: str = "auth_error",
        message: str = "authentication failed",
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.metadata = checked_metadata(metadata or {})


class TransportError(OSError):
    def __init__(
        self,
        code: str = "transport_error",
        message: str = "transport failure",
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.metadata = checked_metadata(metadata or {})


def error_payload(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
