from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from rakathon_backend.b2.auth.keys import KeySet, generate_key_file, load_key_file
from rakathon_backend.b2.auth.models import AuthFailed, StoreUnavailable
from rakathon_backend.b2.auth.normalize import normalize_username
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.service import AuthService
from rakathon_backend.common.errors import ContractError

PW = "correct-horse-battery-staple-x"


def make_keys(tmp_path: Path) -> KeySet:
    target = tmp_path / "auth.key"
    return generate_key_file(target)


def make_service(tmp_path: Path, now: list[int], acct: int = 1000, glob: int = 1000) -> AuthService:
    keys = make_keys(tmp_path)
    db = tmp_path / "auth.db"
    store = SQLiteDemoAuthStore(db)
    store.init_schema()
    provider = LocalPasswordProvider(time_cost=2, memory_cost=19456, parallelism=1)
    return AuthService(
        store=store,
        keys=keys,
        provider=provider,
        clock=lambda: now[0],
        account_limit=acct,
        global_limit=glob,
    )


def test_provision_login_resolve_logout(tmp_path: Path) -> None:
    now = [1000000]
    svc = make_service(tmp_path, now)
    ident = svc.provision_user("jan.novak", PW, "clinician")
    assert ident.role == "clinician"
    assert ident.username == "jan.novak"
    result = svc.login("jan.novak", PW)
    assert len(result.session_token) >= 43
    resolved = svc.resolve(result.session_token)
    assert resolved.user_id == ident.user_id
    assert resolved.username == "jan.novak"
    csrf = svc.csrf_token(result.session_token)
    assert len(csrf) == 64
    svc.logout(result.session_token)
    with pytest.raises(AuthFailed):
        svc.resolve(result.session_token)
    svc.logout(result.session_token)


def test_username_rules() -> None:
    assert normalize_username("Jan.Novak") == "jan.novak"
    assert normalize_username("Šimon.Dvořák") == "šimon.dvořák"
    assert normalize_username("anna-marie.novakova") == "anna-marie.novakova"
    for bad in [
        "",
        "a",
        "a.b.c",
        ".b",
        "a.",
        "a b.c",
        "a/b.c",
        "1a.bc",
        "-a.bc",
        "a--b.c",
        "x." + "y" * 96,
        "admin",
        "a..b",
    ]:
        with pytest.raises(ContractError):
            normalize_username(bad)


def test_password_rules(tmp_path: Path) -> None:
    now = [2000000]
    svc = make_service(tmp_path, now)
    with pytest.raises(ContractError):
        svc.provision_user("jan.novak", "short-pass-123", "viewer")
    with pytest.raises(ContractError):
        svc.provision_user("jan.novak", "x" * 129, "viewer")
    with pytest.raises(ContractError):
        svc.provision_user("jan.novak", PW, "watchdog")
    with pytest.raises(ContractError):
        svc.provision_user("jan.novak", PW, "superuser")


def test_duplicate_and_unknown_generic(tmp_path: Path) -> None:
    now = [3000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jan.novak", PW, "viewer")
    with pytest.raises(ContractError):
        svc.provision_user("jan.novak", "another-long-password-xyz", "viewer")
    with pytest.raises(AuthFailed):
        svc.login("jan.novak", "wrong-wrong-wrong-password")
    with pytest.raises(AuthFailed):
        svc.login("eva.mala", "wrong-wrong-wrong-password")
    try:
        svc.login("jan.novak", "wrong-wrong-wrong-password")
    except AuthFailed as exc:
        assert exc.code == "invalid_credentials"
        assert "jan.novak" not in str(exc)


def test_disabled_user_generic(tmp_path: Path) -> None:
    now = [4000000]
    svc = make_service(tmp_path, now)
    ident = svc.provision_user("jan.novak", PW, "viewer")
    svc.disable_user(ident.user_id)
    with pytest.raises(AuthFailed):
        svc.login("jan.novak", PW)


def test_role_for_user_safe(tmp_path: Path) -> None:
    now = [5000000]
    svc = make_service(tmp_path, now)
    ident = svc.provision_user("jan.novak", PW, "admin")
    assert svc.role_for_user(ident.user_id) == "admin"
    assert svc.role_for_user("0" * 32) is None
    assert svc.role_for_user("not-a-uuid") is None
    svc.disable_user(ident.user_id)
    assert svc.role_for_user(ident.user_id) is None


def test_no_default_accounts(tmp_path: Path) -> None:
    now = [6000000]
    svc = make_service(tmp_path, now)
    with pytest.raises(AuthFailed):
        svc.login("admin.admin", "whatever-long-password-x")
    assert svc.role_for_user("0" * 32) is None


def test_key_roundtrip_secure(tmp_path: Path) -> None:
    target = tmp_path / "k.key"
    keys = generate_key_file(target)
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    loaded = load_key_file(target)
    assert loaded.key_id == keys.key_id
    with pytest.raises(ContractError):
        generate_key_file(target)


def test_logout_store_outage_propagates_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [7000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jan.novak", PW, "viewer")
    token = svc.login("jan.novak", PW).session_token
    assert svc.resolve(token).username == "jan.novak"
    orig = svc.store.delete_session

    def failing(token_hash: str) -> None:
        _ = token_hash
        raise StoreUnavailable()

    monkeypatch.setattr(svc.store, "delete_session", failing)
    with pytest.raises(StoreUnavailable):
        svc.logout(token)
    assert svc.resolve(token).username == "jan.novak"
    monkeypatch.setattr(svc.store, "delete_session", orig)
    svc.logout(token)
    with pytest.raises(AuthFailed):
        svc.resolve(token)
    svc.logout(token)
