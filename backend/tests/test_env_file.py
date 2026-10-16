from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rakathon_backend.cli import _apply_env_file_arg, build_parser
from rakathon_backend.runtime import commands as cmd_module
from rakathon_backend.runtime.env_file import KNOWN_ENV_KEYS, apply_env_file, parse_env_file


def _write(path: Path, body: str, mode: int = 0o600) -> Path:
    path.write_text(body, encoding="utf-8")
    os.chmod(path, mode)
    return path


def test_parse_round_trip(tmp_path: Path) -> None:
    target = _write(
        tmp_path / "ai.env",
        "# comment\n\nRAKATHON_AI_ENABLE=1\nRAKATHON_AI_API_KEY='quoted-value'\nAI_DISABLED=0\n",
    )
    assert parse_env_file(target) == {
        "RAKATHON_AI_ENABLE": "1",
        "RAKATHON_AI_API_KEY": "quoted-value",
        "AI_DISABLED": "0",
    }


def test_double_quotes_and_equals_in_value(tmp_path: Path) -> None:
    target = _write(tmp_path / "ai.env", 'RAKATHON_AI_MODEL="a=b"\n')
    assert parse_env_file(target) == {"RAKATHON_AI_MODEL": "a=b"}


def test_unknown_key_rejected_without_value_leak(tmp_path: Path) -> None:
    target = _write(tmp_path / "ai.env", "EVIL_KEY=topsecretvalue123\n")
    with pytest.raises(ValueError, match="EVIL_KEY"):
        parse_env_file(target)


def test_malformed_line_rejected(tmp_path: Path) -> None:
    target = _write(tmp_path / "ai.env", "RAKATHON_AI_ENABLE\n")
    with pytest.raises(ValueError):
        parse_env_file(target)


def test_symlink_rejected(tmp_path: Path) -> None:
    real = _write(tmp_path / "real.env", "RAKATHON_AI_ENABLE=1\n")
    link = tmp_path / "link.env"
    link.symlink_to(real)
    with pytest.raises(PermissionError):
        parse_env_file(link)


def test_world_readable_rejected(tmp_path: Path) -> None:
    target = _write(tmp_path / "ai.env", "RAKATHON_AI_ENABLE=1\n", mode=0o644)
    with pytest.raises(PermissionError):
        parse_env_file(target)


def test_missing_file_rejected(tmp_path: Path) -> None:
    with pytest.raises((OSError, ValueError, PermissionError)):
        parse_env_file(tmp_path / "nope.env")


def test_known_keys_cover_ai_surface() -> None:
    assert KNOWN_ENV_KEYS >= {
        "RAKATHON_AI_ENABLE",
        "RAKATHON_AI_TRUST_AZURE",
        "RAKATHON_AI_PROVIDER_KIND",
        "RAKATHON_AI_API_KEY",
        "AI_DISABLED",
    }
    assert "PATH" not in KNOWN_ENV_KEYS
    assert "HTTP_PROXY" not in KNOWN_ENV_KEYS


def test_apply_prefers_process_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _write(
        tmp_path / "ai.env",
        "RAKATHON_AI_ENABLE=1\nRAKATHON_AI_MODEL=from-file\n",
    )
    monkeypatch.setenv("RAKATHON_AI_MODEL", "from-process")
    monkeypatch.delenv("RAKATHON_AI_ENABLE", raising=False)
    filled = apply_env_file(target)
    assert os.environ["RAKATHON_AI_MODEL"] == "from-process"
    assert os.environ["RAKATHON_AI_ENABLE"] == "1"
    assert filled == ["RAKATHON_AI_ENABLE"]


def test_key_alone_never_enables_ai(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "RAKATHON_AI_ENABLE",
        "RAKATHON_AI_TRUST_AZURE",
        "RAKATHON_AI_PROVIDER_KIND",
        "RAKATHON_AI_PROVIDER",
        "RAKATHON_AI_MODEL",
        "RAKATHON_AI_BASE_URL",
        "RAKATHON_AI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    target = _write(tmp_path / "ai.env", "RAKATHON_AI_API_KEY=lonely-test-key\n")
    assert apply_env_file(target) == ["RAKATHON_AI_API_KEY"]
    config = cmd_module.ai_config_from_env()
    assert config.ready is False
    assert any("ENABLE" in blocker for blocker in config.blockers)


def test_cli_env_file_flag_exists() -> None:
    for command in ("serve", "ai-check", "client", "health", "demo"):
        argv = ["serve", "--env-file", "x"] if command == "serve" else [command, "--env-file", "x"]
        if command == "client":
            argv = [
                "client",
                "--runtime-dir",
                "x",
                "--user",
                "u",
                "--action",
                "a",
                "--env-file",
                "x",
            ]
        args = build_parser().parse_args(argv)
        assert args.env_file == "x"


def test_cli_rejects_bad_env_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = _write(tmp_path / "ai.env", "EVIL_KEY=1\n")
    args = build_parser().parse_args(["ai-check", "--env-file", str(target)])
    assert _apply_env_file_arg(args) == 2
    body = json.loads(capsys.readouterr().out)
    assert body["error"] == "env_file_rejected"
