from __future__ import annotations

import threading
from pathlib import Path

import pytest

from rakathon_backend.b2.auth.keys import generate_key_file, hash_token
from rakathon_backend.b2.auth.models import AuthFailed, RateLimited, UserRecord
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.service import AuthService
from rakathon_backend.common.errors import ContractError

PW = "correct-horse-battery-staple-x"


class FastProvider(LocalPasswordProvider):
    def __init__(self) -> None:
        super().__init__(time_cost=2, memory_cost=19456, parallelism=1, max_concurrent=1)


def build(
    tmp_path: Path,
    now: list[int],
    provider: LocalPasswordProvider | None = None,
    acct: int = 1000,
    glob: int = 1000,
    audit: list[dict[str, object]] | None = None,
) -> AuthService:
    keys = generate_key_file(tmp_path / "auth.key")
    store = SQLiteDemoAuthStore(tmp_path / "auth.db")
    store.init_schema()
    prov = provider if provider is not None else FastProvider()
    events: list[dict[str, object]] = audit if audit is not None else []
    return AuthService(
        store=store,
        keys=keys,
        provider=prov,
        clock=lambda: now[0],
        account_limit=acct,
        global_limit=glob,
        audit=events.append,
    )


def test_account_rate_limit(tmp_path: Path) -> None:
    now = [10000000]
    svc = build(tmp_path, now, acct=3, glob=1000)
    svc.provision_user("jan.novak", PW, "viewer")
    for _ in range(3):
        with pytest.raises(AuthFailed):
            svc.login("jan.novak", "wrong-wrong-wrong-password")
    with pytest.raises(RateLimited):
        svc.login("jan.novak", "wrong-wrong-wrong-password")
    now[0] += 61
    with pytest.raises(AuthFailed):
        svc.login("jan.novak", "wrong-wrong-wrong-password")


def test_global_rate_limit(tmp_path: Path) -> None:
    now = [11000000]
    svc = build(tmp_path, now, acct=1000, glob=2)
    svc.provision_user("jan.novak", PW, "viewer")
    svc.provision_user("eva.mala", PW, "viewer")
    with pytest.raises(AuthFailed):
        svc.login("jan.novak", "wrong-wrong-wrong-password")
    with pytest.raises(AuthFailed):
        svc.login("eva.mala", "wrong-wrong-wrong-password")
    with pytest.raises(RateLimited):
        svc.login("jan.novak", "wrong-wrong-wrong-password")


def test_hash_gate_overflow_is_429(tmp_path: Path) -> None:
    now = [12000000]
    svc = build(tmp_path, now)
    assert svc.provider.try_acquire() is True
    with pytest.raises(RateLimited):
        svc.login("jan.novak", PW)
    svc.provider.release()


def test_concurrent_resolve_single_winner(tmp_path: Path) -> None:
    now = [13000000]
    svc = build(tmp_path, now)
    svc.provision_user("jan.novak", PW, "viewer")
    token = svc.login("jan.novak", PW).session_token
    digest = hash_token(token)
    first = svc.store.get_session(digest)
    assert first is not None
    wins: list[bool] = []
    now[0] += 5

    def attempt(new_seen: int) -> None:
        wins.append(svc.store.cas_last_seen(digest, first.last_seen, new_seen))

    threads = [threading.Thread(target=attempt, args=(first.last_seen + 5,)) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(1 for item in wins if item) == 1


def test_audit_and_repr_redaction(tmp_path: Path) -> None:
    now = [14000000]
    events: list[dict[str, object]] = []
    svc = build(tmp_path, now, audit=events)
    ident = svc.provision_user("jan.novak", PW, "viewer")
    result = svc.login("jan.novak", PW)
    assert "jan.novak" not in repr(result)
    assert PW not in repr(result)
    assert result.session_token not in repr(ident)
    assert "jan.novak" not in repr(svc.store.get_user_by_id(ident.user_id))
    for event in events:
        blob = str(event)
        assert "jan.novak" not in blob
        assert PW not in blob
        assert result.session_token not in blob
    with pytest.raises(AuthFailed):
        svc.login("jan.novak", "wrong-wrong-wrong-password")
    assert events[-1] == {"event": "login", "user_id": ident.user_id, "status": "failed"}


def test_malformed_hash_clamped(tmp_path: Path) -> None:
    now = [15000000]
    svc = build(tmp_path, now)
    ident = svc.provision_user("jan.novak", PW, "viewer")
    rec = svc.store.get_user_by_id(ident.user_id)
    assert rec is not None
    evil = "$argon2id$v=19$m=1048576,t=20,p=4$" + "A" * 64 + "$" + "B" * 64
    corrupted = UserRecord(
        user_id=rec.user_id,
        username_index=rec.username_index,
        password_hash=evil,
        enc_nonce=bytes(rec.enc_nonce),
        enc_ct=bytes(rec.enc_ct),
        key_id=rec.key_id,
        role=rec.role,
        active=rec.active,
        auth_version=rec.auth_version,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )
    svc.store.update_user(corrupted)
    with pytest.raises(AuthFailed):
        svc.login("jan.novak", PW)


def test_prod_defaults_meet_minimum() -> None:
    provider = LocalPasswordProvider()
    params = provider.hasher._parameters
    assert params.memory_cost >= 19456
    assert params.time_cost >= 2
    assert params.parallelism >= 1
    with pytest.raises(ContractError):
        provider.verify("not-a-hash", PW)


def test_malformed_username_generic_and_ratelimited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_dir = tmp_path / "a"
    first_dir.mkdir(mode=0o700)
    now = [16000000]
    svc = build(first_dir, now, acct=2, glob=1000)
    svc.provision_user("jan.novak", PW, "viewer")
    calls = [0]
    orig = svc.provider.dummy_verify

    def counting() -> None:
        calls[0] += 1
        orig()

    monkeypatch.setattr(svc.provider, "dummy_verify", counting)
    bads = ["badnodot", "a b.c", "a\x01b.c", "a..b", "admin", "x." + "y" * 100]
    for bad in bads:
        with pytest.raises(AuthFailed):
            svc.login(bad, "wrong-wrong-wrong-password")
    assert calls[0] == len(bads)
    with pytest.raises(ContractError):
        svc.provision_user("badnodot", PW, "viewer")
    second_dir = tmp_path / "b"
    second_dir.mkdir(mode=0o700)
    now2 = [17000000]
    svc2 = build(second_dir, now2, acct=2, glob=1000)
    svc2.provision_user("eva.mala", PW, "viewer")
    with pytest.raises(AuthFailed):
        svc2.login("badnodot", "wrong-wrong-wrong-password")
    with pytest.raises(AuthFailed):
        svc2.login("badnodot", "wrong-wrong-wrong-password")
    with pytest.raises(RateLimited):
        svc2.login("badnodot", "wrong-wrong-wrong-password")
