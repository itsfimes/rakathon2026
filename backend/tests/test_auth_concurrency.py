from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from rakathon_backend.b2.auth.keys import generate_key_file, hash_token
from rakathon_backend.b2.auth.models import AuthFailed
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.service import AuthService

PW = "correct-horse-battery-staple-x"


def make_service(tmp_path: Path, now: list[int]) -> AuthService:
    keys = generate_key_file(tmp_path / "auth.key")
    store = SQLiteDemoAuthStore(tmp_path / "auth.db")
    store.init_schema()
    provider = LocalPasswordProvider(time_cost=2, memory_cost=19456, parallelism=1)
    return AuthService(
        store=store,
        keys=keys,
        provider=provider,
        clock=lambda: now[0],
        account_limit=10000,
        global_limit=10000,
    )


def test_parallel_resolve_same_tick_all_succeed(tmp_path: Path) -> None:
    now = [20000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jan.novak", PW, "viewer")
    token = svc.login("jan.novak", PW).session_token
    now[0] += 7
    barrier = threading.Barrier(8)
    outcomes: list[bool] = []

    def attempt() -> None:
        barrier.wait(timeout=10.0)
        try:
            svc.resolve(token)
            outcomes.append(True)
        except AuthFailed:
            outcomes.append(False)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(outcomes) == 8
    assert all(outcomes)
    assert svc.resolve(token).username == "jan.novak"


def test_parallel_resolve_across_ticks_all_succeed(tmp_path: Path) -> None:
    now = [21000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jan.novak", PW, "viewer")
    token = svc.login("jan.novak", PW).session_token
    barrier = threading.Barrier(6)
    outcomes: list[bool] = []
    ticks = [3, 5, 9, 12, 20, 31]

    def attempt(delta: int) -> None:
        barrier.wait(timeout=10.0)
        local = [now[0] + delta]
        rated = AuthService(
            store=svc.store,
            keys=svc.keys,
            provider=svc.provider,
            clock=lambda: local[0],
            account_limit=10000,
            global_limit=10000,
        )
        try:
            rated.resolve(token)
            outcomes.append(True)
        except AuthFailed:
            outcomes.append(False)

    threads = [threading.Thread(target=attempt, args=(tick,)) for tick in ticks]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(outcomes) == 6
    assert all(outcomes)


def test_logout_race_fails_closed(tmp_path: Path) -> None:
    now = [22000000]
    svc = make_service(tmp_path, now)
    svc.provision_user("jan.novak", PW, "viewer")
    token = svc.login("jan.novak", PW).session_token
    now[0] += 4
    barrier = threading.Barrier(2)
    resolved: list[bool] = []

    def resolve_now() -> None:
        barrier.wait(timeout=10.0)
        try:
            svc.resolve(token)
            resolved.append(True)
        except AuthFailed:
            resolved.append(False)

    def logout_now() -> None:
        barrier.wait(timeout=10.0)
        svc.logout(token)

    first = threading.Thread(target=resolve_now)
    second = threading.Thread(target=logout_now)
    first.start()
    second.start()
    first.join()
    second.join()
    assert len(resolved) == 1
    with pytest.raises(AuthFailed):
        svc.resolve(token)
    conn = sqlite3.connect(str(tmp_path / "auth.db"))
    try:
        remaining = [str(row[0]) for row in conn.execute("SELECT token_hash FROM auth_sessions")]
    finally:
        conn.close()
    assert hash_token(token) not in remaining


def test_disable_race_fails_closed(tmp_path: Path) -> None:
    now = [23000000]
    svc = make_service(tmp_path, now)
    ident = svc.provision_user("jan.novak", PW, "viewer")
    token = svc.login("jan.novak", PW).session_token
    now[0] += 4
    barrier = threading.Barrier(2)
    failures: list[bool] = []

    def resolve_now() -> None:
        barrier.wait(timeout=10.0)
        try:
            svc.resolve(token)
        except AuthFailed:
            failures.append(True)

    def disable_now() -> None:
        barrier.wait(timeout=10.0)
        svc.disable_user(ident.user_id)

    first = threading.Thread(target=resolve_now)
    second = threading.Thread(target=disable_now)
    first.start()
    second.start()
    first.join()
    second.join()
    with pytest.raises(AuthFailed):
        svc.resolve(token)


def test_role_change_race_fails_closed(tmp_path: Path) -> None:
    now = [24000000]
    svc = make_service(tmp_path, now)
    ident = svc.provision_user("jan.novak", PW, "viewer")
    token = svc.login("jan.novak", PW).session_token
    now[0] += 4
    svc.set_role(ident.user_id, "clinician")
    with pytest.raises(AuthFailed):
        svc.resolve(token)
    fresh = svc.login("jan.novak", PW).session_token
    assert svc.resolve(fresh).role == "clinician"
