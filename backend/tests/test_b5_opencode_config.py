from __future__ import annotations

import json
from pathlib import Path

import pytest

from rakathon_backend.b5.opencode.config import from_env
from rakathon_backend.b5.opencode.validation import build_config_content, validate_base_url


def _full_env() -> dict[str, str]:
    return {
        "RAKATHON_AI_ENABLE": "1",
        "RAKATHON_AI_OS_EGRESS_ISOLATED": "1",
        "RAKATHON_AI_PROVIDER": "local",
        "RAKATHON_AI_MODEL": "tiny",
        "RAKATHON_AI_BASE_URL": "http://127.0.0.1:11434",
    }


def test_full_env_enables() -> None:
    config = from_env(_full_env(), requested=True)
    assert config.ready is True
    assert config.blockers == ()
    assert config.base_url == "http://127.0.0.1:11434"


def test_not_requested_never_enables() -> None:
    config = from_env(_full_env(), requested=False)
    assert config.ready is False
    assert config.enabled is False


def test_missing_opt_in_blocks() -> None:
    env = _full_env()
    del env["RAKATHON_AI_ENABLE"]
    config = from_env(env, requested=True)
    assert config.ready is False
    assert any("ENABLE" in blocker for blocker in config.blockers)


def test_missing_attestation_blocks() -> None:
    env = _full_env()
    del env["RAKATHON_AI_OS_EGRESS_ISOLATED"]
    config = from_env(env, requested=True)
    assert config.ready is False
    assert any("EGRESS" in blocker for blocker in config.blockers)


def test_missing_provider_model_blocks() -> None:
    env = _full_env()
    del env["RAKATHON_AI_PROVIDER"]
    del env["RAKATHON_AI_MODEL"]
    config = from_env(env, requested=True)
    assert config.ready is False
    assert len(config.blockers) >= 2


def test_ai_disabled_blocks() -> None:
    env = _full_env()
    env["AI_DISABLED"] = "1"
    config = from_env(env, requested=True)
    assert config.ready is False


def test_kill_file_blocks(tmp_path: Path) -> None:
    target = tmp_path / "kill"
    target.write_text("stop", encoding="utf-8")
    env = _full_env()
    env["RAKATHON_AI_KILL_FILE"] = str(target)
    config = from_env(env, requested=True)
    assert config.ready is False
    assert any("kill file" in blocker for blocker in config.blockers)


def test_missing_kill_file_is_fine() -> None:
    env = _full_env()
    env["RAKATHON_AI_KILL_FILE"] = "/tmp/opencode/rak-test-no-such-kill-file"
    config = from_env(env, requested=True)
    assert config.ready is True


def test_loopback_ipv6_accepted() -> None:
    assert validate_base_url("http://[::1]:8080/v1") == "http://[::1]:8080/v1"


def test_loopback_ipv4_with_path_kept() -> None:
    assert validate_base_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"


@pytest.mark.parametrize(
    "raw",
    [
        "http://localhost:11434",
        "http://LOCALHOST:11434",
        "http://0.0.0.0:11434",
        "http://192.168.1.2:11434",
        "https://127.0.0.1:11434",
        "http://127.0.0.1/",
        "http://127.0.0.1",
        "http://user:pass@127.0.0.1:11434",
        "http://127.0.0.1:11434/v1?key=x",
        "http://127.0.0.1:11434/v1#frag",
        "http://127.0.0.2:11434",
        "",
        "not-a-url",
    ],
)
def test_non_loopback_or_unsafe_base_url_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        validate_base_url(raw)


def test_cloud_url_blocks_even_when_opted_in() -> None:
    env = _full_env()
    env["RAKATHON_AI_BASE_URL"] = "https://api.example.com/v1"
    config = from_env(env, requested=True)
    assert config.ready is False
    assert config.base_url == ""


def test_binary_default_and_pin() -> None:
    config = from_env(_full_env(), requested=True)
    assert config.binary == "opencode"
    assert config.expected_version == "2.0.31"


def test_custom_binary_and_pin() -> None:
    env = _full_env()
    env["RAKATHON_AI_BINARY"] = "/usr/local/bin/opencode"
    env["RAKATHON_AI_EXPECTED_VERSION"] = "2.0.31"
    config = from_env(env, requested=True)
    assert config.binary == "/usr/local/bin/opencode"
    assert config.ready is True


def test_child_config_carries_provider_and_deny() -> None:
    content = json.loads(build_config_content("local", "tiny", "http://127.0.0.1:11434"))
    provider = content["provider"]["local"]
    assert provider["options"]["baseURL"] == "http://127.0.0.1:11434"
    assert provider["models"] == {"tiny": {"name": "tiny"}}
    assert content["permission"] == "deny"
    assert content["model"] == "local/tiny"
    assert isinstance(content["policies"], list)
    assert content["policies"] != []
