from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rakathon_backend.b2.auth.keys import (
    blind_index,
    decrypt_username,
    encrypt_username,
    generate_key_file,
    hash_token,
)
from rakathon_backend.b2.auth.models import AuthFailed
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.service import AuthService
from rakathon_backend.common.errors import ContractError

PW = "correct-horse-battery-staple-x"
PW2 = "another-long-demo-password-xyz"


def build(tmp_path: Path, now: list[int]) -> AuthService:
    keys_path = tmp_path / "auth.key"
    keys = generate_key_file(keys_path)
    store = SQLiteDemoAuthStore(tmp_path / "auth.db")
    store.init_schema()
    provider = LocalPasswordProvider(time_cost=2, memory_cost=19456, parallelism=1)
    return AuthService(
        store=store,
        keys=keys,
        provider=provider,
        clock=lambda: now[0],
        account_limit=1000,
        global_limit=1000,
    )


def test_persist_restart_no_plaintext(tmp_path: Path) -> None:
    now = [7000000]
    svc = build(tmp_path, now)
    ident = svc.provision_user("jan.novak", PW, "clinician")
    token = svc.login("jan.novak", PW).session_token
    assert svc.resolve(token).user_id == ident.user_id
    db_path = tmp_path / "auth.db"
    raw = db_path.read_bytes()
    assert b"jan.novak" not in raw
    assert PW.encode() not in raw
    assert token.encode() not in raw
    conn = sqlite3.connect(str(db_path))
    try:
        users = conn.execute("SELECT password_hash, enc_nonce, enc_ct FROM auth_users").fetchall()
        sessions = conn.execute("SELECT token_hash FROM auth_sessions").fetchall()
    finally:
        conn.close()
    assert len(users) == 1
    assert str(users[0][0]).startswith("$argon2id$")
    assert sessions[0][0] == hash_token(token)
    svc2 = AuthService(
        store=SQLiteDemoAuthStore(db_path),
        keys=svc.keys,
        provider=svc.provider,
        clock=lambda: now[0],
        account_limit=1000,
        global_limit=1000,
    )
    assert svc2.resolve(token).username == "jan.novak"


def test_wrong_key_and_aad_fail(tmp_path: Path) -> None:
    now = [8000000]
    svc = build(tmp_path, now)
    ident = svc.provision_user("jan.novak", PW, "viewer")
    rec = svc.store.get_user_by_id(ident.user_id)
    assert rec is not None
    other_keys = generate_key_file(tmp_path / "other.key")
    with pytest.raises(ContractError):
        decrypt_username(other_keys.aead_key, rec.user_id, bytes(rec.enc_nonce), bytes(rec.enc_ct))
    nonce, ct = encrypt_username(svc.keys.aead_key, rec.user_id, "jan.novak")
    tampered = bytes([ct[0] ^ 1]) + bytes(ct[1:])
    with pytest.raises(ContractError):
        decrypt_username(svc.keys.aead_key, rec.user_id, nonce, tampered)
    with pytest.raises(ContractError):
        decrypt_username(svc.keys.aead_key, "0" * 32, nonce, ct)


def test_expiry_idle_logout_disable_role(tmp_path: Path) -> None:
    now = [9000000]
    svc = build(tmp_path, now)
    ident = svc.provision_user("jan.novak", PW, "viewer")
    token = svc.login("jan.novak", PW).session_token
    now[0] += 8 * 3600
    with pytest.raises(AuthFailed):
        svc.resolve(token)
    now[0] = 9100000
    token2 = svc.login("jan.novak", PW).session_token
    now[0] += 15 * 60
    with pytest.raises(AuthFailed):
        svc.resolve(token2)
    now[0] = 9200000
    token3 = svc.login("jan.novak", PW).session_token
    svc.set_role(ident.user_id, "clinician")
    with pytest.raises(AuthFailed):
        svc.resolve(token3)
    now[0] = 9300000
    token4 = svc.login("jan.novak", PW).session_token
    assert svc.resolve(token4).role == "clinician"
    svc.set_password(ident.user_id, PW2)
    with pytest.raises(AuthFailed):
        svc.resolve(token4)
    login_after = svc.login("jan.novak", PW2)
    assert svc.resolve(login_after.session_token).username == "jan.novak"
    svc.disable_user(ident.user_id)
    with pytest.raises(AuthFailed):
        svc.resolve(login_after.session_token)


def test_lastseen_cas_monotonic(tmp_path: Path) -> None:
    now = [9400000]
    svc = build(tmp_path, now)
    svc.provision_user("jan.novak", PW, "viewer")
    token = svc.login("jan.novak", PW).session_token
    digest = hash_token(token)
    first = svc.store.get_session(digest)
    assert first is not None
    now[0] += 10
    assert svc.resolve(token).username == "jan.novak"
    assert svc.store.cas_last_seen(digest, first.last_seen, first.last_seen) is False
    assert svc.resolve(token).username == "jan.novak"


def test_index_binds_username(tmp_path: Path) -> None:
    now = [9500000]
    svc = build(tmp_path, now)
    svc.provision_user("jan.novak", PW, "viewer")
    idx = blind_index(svc.keys.index_key, "jan.novak")
    rec = svc.store.get_user_by_index(idx)
    assert rec is not None
    assert rec.username_index == idx
    assert svc.store.get_user_by_index(blind_index(svc.keys.index_key, "eva.mala")) is None
