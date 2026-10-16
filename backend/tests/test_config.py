import json

import pytest

from rakathon_backend.common.config import ConfigError, demo_config, load_from_env


def test_defaults() -> None:
    cfg = load_from_env({})
    assert cfg.mode == "mock"
    assert cfg.service_tokens == {}


def test_tokens_from_json_and_prefix() -> None:
    long_token = "t" * 40
    cfg = load_from_env(
        {
            "RAKATHON_MODE": "mock",
            "RAKATHON_SERVICE_TOKENS": json.dumps({"b4": long_token}),
            "RAKATHON_TOKEN_B6": long_token,
        }
    )
    assert cfg.service_tokens["b4"] == long_token
    assert cfg.service_tokens["b6"] == long_token
    assert cfg.token_registry()[long_token] in {"b4", "b6"}


def test_weak_token_rejected_outside_demo() -> None:
    with pytest.raises(ConfigError):
        load_from_env({"RAKATHON_MODE": "prod", "RAKATHON_SERVICE_TOKENS": json.dumps({"b4": "x"})})


def test_bad_json_rejected() -> None:
    with pytest.raises(ConfigError):
        load_from_env({"RAKATHON_SERVICE_TOKENS": "{nope"})


def test_demo_generates_tokens() -> None:
    cfg = demo_config()
    assert cfg.mode == "demo"
    assert len(cfg.service_tokens) == 3
    assert len({*cfg.service_tokens.values()}) == 3
