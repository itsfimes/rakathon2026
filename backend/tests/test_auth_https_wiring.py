from __future__ import annotations

from pathlib import Path

import pytest

from rakathon_backend.b2.auth.https_config import SERVICE_URL
from rakathon_backend.b2.auth.https_store import IrisHTTPSAuthStore
from rakathon_backend.cli import build_parser
from rakathon_backend.common.errors import ContractError
from rakathon_backend.runtime.auth_cmds import _store_for, cmd_auth_init
from rakathon_backend.runtime.auth_serve import _auth_store_for, cmd_auth_serve
from rakathon_backend.runtime.env_file import parse_env_file


def configured_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAKATHON_AUTH_HTTPS_URL", SERVICE_URL)
    monkeypatch.setenv("RAKATHON_AUTH_HTTPS_NAMESPACE", "USER")
    monkeypatch.setenv("RAKATHON_AUTH_HTTPS_CREDENTIALS", "dedicated")
    monkeypatch.setenv("RAKATHON_AUTH_HTTPS_USER", "synthetic-service")
    monkeypatch.setenv("RAKATHON_AUTH_HTTPS_PASSWORD", "synthetic-secret")


def test_env_file_accepts_only_explicit_auth_keys(tmp_path: Path) -> None:
    path = tmp_path / "private.env"
    path.write_text(
        f"RAKATHON_AUTH_HTTPS_URL={SERVICE_URL}\nRAKATHON_AUTH_HTTPS_NAMESPACE=USER\n"
        "RAKATHON_AUTH_HTTPS_CREDENTIALS=dedicated\nRAKATHON_AUTH_HTTPS_USER=synthetic\n"
        "RAKATHON_AUTH_HTTPS_PASSWORD=synthetic-secret\n"
    )
    path.chmod(0o600)
    assert parse_env_file(path)["RAKATHON_AUTH_HTTPS_NAMESPACE"] == "USER"
    path.write_text(path.read_text() + "RAKATHON_AUTH_HTTPS_ALLOW_INSECURE=1\n")
    with pytest.raises(ValueError, match="unknown key"):
        parse_env_file(path)


def test_explicit_https_store_dispatch_has_no_database_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured_env(monkeypatch)
    assert isinstance(_store_for("iris-https", tmp_path), IrisHTTPSAuthStore)
    assert isinstance(_auth_store_for("iris-https", tmp_path), IrisHTTPSAuthStore)
    monkeypatch.delenv("RAKATHON_AUTH_HTTPS_URL")
    with pytest.raises(ContractError):
        _store_for("iris-https", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_missing_config_init_fails_before_creating_any_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("RAKATHON_AUTH_HTTPS_CREDENTIALS", raising=False)
    target = tmp_path / "auth"
    assert cmd_auth_init("iris-https", str(target)) == 1
    assert not target.exists()


def test_https_init_only_creates_local_keys_not_schema(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured_env(monkeypatch)

    def forbidden_init(self: IrisHTTPSAuthStore) -> None:
        pytest.fail("runtime schema initialization is forbidden")

    monkeypatch.setattr(IrisHTTPSAuthStore, "init_schema", forbidden_init)
    target = tmp_path / "auth"
    assert cmd_auth_init("iris-https", str(target)) == 0
    assert {p.name for p in target.iterdir()} == {"auth.authkey", "proxy.key"}
    original = {p.name: p.read_bytes() for p in target.iterdir()}
    assert cmd_auth_init("iris-https", str(target)) == 2
    assert original == {p.name: p.read_bytes() for p in target.iterdir()}


@pytest.mark.parametrize(
    "command", ["auth-init", "auth-user-add", "auth-user-disable", "auth-serve"]
)
def test_cli_accepts_explicit_https_store_after_subcommand(command: str) -> None:
    argv = [
        command,
        "--auth-store",
        "iris-https",
        "--auth-dir",
        "/private/auth",
        "--env-file",
        "/private/auth.env",
    ]
    if command == "auth-user-add":
        argv += ["--username", "synthetic.user", "--role", "viewer"]
    elif command == "auth-user-disable":
        argv += ["--user-id", "a" * 32]
    elif command == "auth-serve":
        argv += ["--origin", "http://localhost:5174", "--storage", "iris-fhir"]
    args = build_parser().parse_args(argv)
    assert args.auth_store == "iris-https" and args.env_file == "/private/auth.env"


@pytest.mark.asyncio
async def test_https_serve_does_not_fall_back_to_mock_clinical_storage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    configured_env(monkeypatch)
    target = tmp_path / "auth"
    assert cmd_auth_init("iris-https", str(target)) == 0
    args = build_parser().parse_args(
        [
            "auth-serve",
            "--auth-store",
            "iris-https",
            "--auth-dir",
            str(target),
            "--origin",
            "http://localhost:5174",
            "--allow-loopback-http",
        ]
    )
    assert await cmd_auth_serve(args) == 2
    assert "iris_https_requires_iris_fhir_storage" in capsys.readouterr().out
