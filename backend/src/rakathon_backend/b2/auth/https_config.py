from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from rakathon_backend.common.errors import ContractError

SERVICE_URL = "https://iris.racek.xyz/auth-storage/v1/operation"
TEST_PATH = "/auth-storage/v1/operation"


def _invalid() -> ContractError:
    return ContractError(code="not_configured", message="auth HTTPS is not configured")


@dataclass(frozen=True, slots=True)
class AuthHTTPSConfig:
    url: str
    username: str = field(repr=False)
    password: str = field(repr=False)
    namespace: str = "USER"
    allow_test_loopback: bool = False

    def __post_init__(self) -> None:
        if self.namespace != "USER" or not self.username or not self.password:
            raise _invalid()
        if any(ord(c) < 32 or ord(c) == 127 for c in self.username + self.password):
            raise _invalid()
        if len(self.username) > 256 or len(self.password) > 1024 or ":" in self.username:
            raise _invalid()
        if self.url == SERVICE_URL:
            return
        try:
            parts = urlsplit(self.url)
            valid = (
                self.allow_test_loopback
                and parts.scheme == "http"
                and parts.hostname == "127.0.0.1"
                and parts.port is not None
                and 1 <= parts.port <= 65535
                and parts.netloc == f"127.0.0.1:{parts.port}"
                and parts.path == TEST_PATH
                and not parts.query
                and not parts.fragment
                and "?" not in self.url
                and "#" not in self.url
            )
        except ValueError:
            raise _invalid() from None
        if not valid:
            raise _invalid()

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AuthHTTPSConfig:
        source = os.environ if env is None else env
        selection = source.get("RAKATHON_AUTH_HTTPS_CREDENTIALS", "")
        if selection == "fhir":
            if source.get("RAKATHON_IRIS_FHIR_BASE_URL", "").rstrip("/") != (
                "https://iris.racek.xyz/fhir/r4"
            ):
                raise _invalid()
            user = source.get("RAKATHON_IRIS_FHIR_USER", "")
            password = source.get("RAKATHON_IRIS_FHIR_PASSWORD", "")
        elif selection == "dedicated":
            user = source.get("RAKATHON_AUTH_HTTPS_USER", "")
            password = source.get("RAKATHON_AUTH_HTTPS_PASSWORD", "")
        else:
            raise _invalid()
        return cls(
            url=source.get("RAKATHON_AUTH_HTTPS_URL", ""),
            username=user,
            password=password,
            namespace=source.get("RAKATHON_AUTH_HTTPS_NAMESPACE", ""),
        )
