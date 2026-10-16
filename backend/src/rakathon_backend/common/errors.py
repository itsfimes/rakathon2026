from __future__ import annotations


class ContractError(ValueError):
    def __init__(self, code: str = "contract_error", message: str = "invalid envelope") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AuthError(PermissionError):
    def __init__(self, code: str = "auth_error", message: str = "authentication failed") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TransportError(OSError):
    def __init__(self, code: str = "transport_error", message: str = "transport failure") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def error_payload(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
