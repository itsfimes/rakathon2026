from __future__ import annotations

import os
import secrets
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rakathon_backend.b2.auth.keys import KeySet, load_key_file
from rakathon_backend.b2.auth.protocol import PersistentAuthStore
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b5.gateway import AIAdapter, KillSwitch
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.service import AuthService
from rakathon_backend.common.errors import ContractError
from rakathon_backend.common.ipc import UnixJsonClient
from rakathon_backend.common.rpc import make_client
from rakathon_backend.runtime.application import BackendApp
from rakathon_backend.runtime.tokens import FRONTEND_USERS, SERVICES

AUTH_KEY_NAME = "auth.authkey"
AUTH_DB_NAME = "users.auth.db"
PROXY_KEY_NAME = "proxy.key"
WEB_SOURCE = "web:auth"
AUTH_SERVICE_NAME = "b7"


@dataclass
class AuthBundle:
    service: AuthService
    role_resolver: Callable[[str], str | None]
    is_privileged: Callable[[str], bool]
    web_sources: frozenset[str]


def fresh_tokens_with_auth(base: dict[str, str] | None = None) -> dict[str, str]:
    tokens = dict(base) if base else {}
    for name in list(SERVICES) + [f"frontend:{u}" for u in FRONTEND_USERS]:
        tokens.setdefault(name, secrets.token_urlsafe(32))
    tokens.setdefault(AUTH_SERVICE_NAME, secrets.token_urlsafe(32))
    tokens.setdefault(WEB_SOURCE, secrets.token_urlsafe(32))
    return tokens


def check_auth_dir(path: Path, *, must_exist: bool = True) -> Path:
    target = Path(path)
    try:
        st = target.lstat()
    except OSError as exc:
        raise ContractError(code="not_configured", message="auth dir unavailable") from exc
    if not stat.S_ISDIR(st.st_mode):
        raise ContractError(code="not_configured", message="auth dir unavailable")
    try:
        if st.st_uid != os.geteuid():
            raise ContractError(code="not_configured", message="auth dir unavailable")
    except AttributeError:
        pass
    if (st.st_mode & 0o077) != 0:
        raise ContractError(code="not_configured", message="auth dir unavailable")
    if not must_exist:
        return target
    return target


def create_auth_dir(path: Path) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise ContractError(code="already_exists", message="auth dir exists")
    try:
        target.mkdir(mode=0o700, parents=False, exist_ok=False)
    except OSError as exc:
        raise ContractError(code="not_configured", message="auth dir unavailable") from exc
    try:
        os.chmod(str(target), 0o700)
    except OSError:
        pass
    return check_auth_dir(target)


def key_path_for(auth_dir: Path) -> Path:
    return Path(auth_dir) / AUTH_KEY_NAME


def db_path_for(auth_dir: Path) -> Path:
    return Path(auth_dir) / AUTH_DB_NAME


def proxy_path_for(auth_dir: Path) -> Path:
    return Path(auth_dir) / PROXY_KEY_NAME


def open_demo_store(auth_dir: Path) -> SQLiteDemoAuthStore:
    check_auth_dir(auth_dir)
    return SQLiteDemoAuthStore(db_path_for(auth_dir))


def load_auth_service(
    auth_dir: Path,
    store: PersistentAuthStore,
    *,
    provider: LocalPasswordProvider | None = None,
) -> tuple[AuthService, KeySet]:
    check_auth_dir(auth_dir)
    keys = load_key_file(key_path_for(auth_dir))
    active = provider if provider is not None else LocalPasswordProvider()
    return (AuthService(store=store, keys=keys, provider=active), keys)


def role_resolver_for(service: AuthService) -> Callable[[str], str | None]:
    def resolve(user_id: str) -> str | None:
        if user_id == "web-assistant":
            return "web-assistant"
        return service.role_for_user(user_id)

    return resolve


def privilege_check_for(service: AuthService) -> Callable[[str], bool]:
    def allowed(user_id: str) -> bool:
        if user_id == "watchdog":
            return True
        try:
            role = service.role_for_user(user_id)
        except (ContractError, OSError, ValueError, KeyError, RuntimeError):
            return False
        except (AttributeError, TypeError):
            return False
        return role in ("admin", "coordinator")

    return allowed


def make_bundle(service: AuthService) -> AuthBundle:
    return AuthBundle(
        service=service,
        role_resolver=role_resolver_for(service),
        is_privileged=privilege_check_for(service),
        web_sources=frozenset({WEB_SOURCE}),
    )


def web_client_for(app: BackendApp, target: str = "b4") -> UnixJsonClient:
    return make_client(
        app.runtime_dir, target=target, source=WEB_SOURCE, token=app.tokens[WEB_SOURCE]
    )


def build_auth_app(
    runtime_dir: Path,
    tokens: dict[str, str],
    service: AuthService,
    *,
    store: Any | None = None,
    mode: str = "mock",
    screening: Any | None = None,
    ai_adapter: AIAdapter | None = None,
    ai_mode: str = "mock",
    kill_file: Path | str | None = None,
    kill_switch: KillSwitch | None = None,
) -> BackendApp:
    if AUTH_SERVICE_NAME not in tokens or WEB_SOURCE not in tokens:
        raise ContractError(code="not_configured", message="auth tokens are missing")
    return BackendApp(
        runtime_dir,
        dict(tokens),
        store=store,
        mode=mode,
        screening=screening,
        auth=make_bundle(service),
        ai_adapter=ai_adapter,
        ai_mode=ai_mode,
        kill_file=kill_file,
        kill_switch=kill_switch,
    )
