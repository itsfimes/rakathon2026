from __future__ import annotations

import httpx
import pytest

from rakathon_backend.b2.iris.config import IrisFhirConfig
from rakathon_backend.b2.iris.fhir import DirectFhirAdapter
from rakathon_backend.common.errors import ContractError

LOOPBACK_HTTP = "http://127.0.0.1:8765/fhir/r4"


def _adapter(handler: httpx.BaseTransport, base: str = LOOPBACK_HTTP) -> DirectFhirAdapter:
    client = httpx.Client(
        transport=handler,
        base_url=base,
        trust_env=False,
        follow_redirects=False,
    )
    config = IrisFhirConfig(base_url=base, username="u", password="p")
    return DirectFhirAdapter(config, client=client)


def test_non_loopback_base_rejected() -> None:
    config = IrisFhirConfig(base_url="https://iris.example/fhir/r4", username="u", password="p")
    with pytest.raises(ContractError):
        DirectFhirAdapter(config, client=None)


def test_loopback_http_allowed_with_flag() -> None:
    env = {
        "RAKATHON_IRIS_FHIR_BASE_URL": LOOPBACK_HTTP,
        "RAKATHON_IRIS_FHIR_USER": "u",
        "RAKATHON_IRIS_FHIR_PASSWORD": "p",
    }
    with pytest.raises(ContractError):
        IrisFhirConfig.from_env(env)
    cfg = IrisFhirConfig.from_env(env, allow_insecure_loopback=True)
    assert cfg.base_url == LOOPBACK_HTTP
    assert cfg.verify_tls is True


def test_loopback_http_read_roundtrip() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("http://127.0.0.1:8765/")
        return httpx.Response(200, json={"resourceType": "Patient", "id": "p1"})

    found = _adapter(httpx.MockTransport(handler)).read("Patient", "p1")
    assert found is not None and found["id"] == "p1"


def test_https_loopback_still_ok() -> None:
    env = {
        "RAKATHON_IRIS_FHIR_BASE_URL": "https://127.0.0.1:8888/fhir/r4",
        "RAKATHON_IRIS_FHIR_USER": "u",
        "RAKATHON_IRIS_FHIR_PASSWORD": "p",
        "RAKATHON_IRIS_FHIR_VERIFY_TLS": "0",
    }
    cfg = IrisFhirConfig.from_env(env)
    assert cfg.verify_tls is False
    adapter = DirectFhirAdapter(cfg, client=None)
    assert adapter is not None


def test_password_not_in_repr() -> None:
    cfg = IrisFhirConfig(base_url=LOOPBACK_HTTP, username="u", password="secret-pw")
    assert "secret-pw" not in repr(cfg)
