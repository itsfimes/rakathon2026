from __future__ import annotations

import getpass
import json
from pathlib import Path
from typing import Any

from rakathon_backend.b2.auth.iris_store import IrisAuthStore
from rakathon_backend.b2.auth.keys import generate_key_file, load_key_file
from rakathon_backend.b2.auth.sqlite_store import SQLiteDemoAuthStore
from rakathon_backend.b2.iris.config import IrisSqlConfig
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.service import AuthService
from rakathon_backend.common.errors import ContractError
from rakathon_backend.runtime.auth_bundle import (
    check_auth_dir,
    create_auth_dir,
    db_path_for,
    key_path_for,
    load_auth_service,
    proxy_path_for,
)
from rakathon_backend.web.config import generate_proxy_key


def _store_for(auth_store: str, auth_dir: Path) -> Any:
    if auth_store == "demo":
        return SQLiteDemoAuthStore(db_path_for(auth_dir))
    if auth_store == "iris":
        config = IrisSqlConfig.from_env()
        return IrisAuthStore(config)
    raise ContractError(code="not_configured", message="auth store unknown")


def cmd_auth_init(auth_store: str, auth_dir: str) -> int:
    if auth_store not in ("demo", "iris"):
        print(json.dumps({"error": "auth store must be demo or iris"}))
        return 2
    try:
        target = create_auth_dir(Path(auth_dir))
    except ContractError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        return 2
    try:
        generate_key_file(key_path_for(target))
    except ContractError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        return 1
    try:
        generate_proxy_key(proxy_path_for(target))
    except ContractError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        return 1
    if auth_store == "demo":
        store = SQLiteDemoAuthStore(db_path_for(target))
        try:
            store.init_schema()
        except ContractError as exc:
            print(json.dumps({"error": exc.code, "message": exc.message}))
            return 1
    else:
        try:
            store_iris = _store_for("iris", target)
            store_iris.init_schema()
        except ContractError as exc:
            print(json.dumps({"error": exc.code, "message": exc.message}))
            return 1
    print(
        json.dumps(
            {
                "initialized": True,
                "authDir": str(target),
                "authStore": auth_store,
                "keyFile": str(key_path_for(target)),
                "proxyFile": str(proxy_path_for(target)),
            }
        )
    )
    return 0


def _prompt_password() -> str | None:
    try:
        first = getpass.getpass("Password: ")
        second = getpass.getpass("Confirm password: ")
    except (OSError, ValueError, EOFError):
        return None
    if first != second or not first:
        return None
    return first


def cmd_auth_user_add(auth_store: str, auth_dir: str, username: str, role: str) -> int:
    if auth_store not in ("demo", "iris"):
        print(json.dumps({"error": "auth store must be demo or iris"}))
        return 2
    target = Path(auth_dir)
    try:
        check_auth_dir(target)
        store = _store_for(auth_store, target)
        service, _ = load_auth_service(target, store, provider=LocalPasswordProvider())
    except ContractError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        return 1
    password = _prompt_password()
    if password is None:
        print(json.dumps({"error": "password mismatch or unreadable"}))
        return 2
    try:
        identity = service.provision_user(username, password, role)
    except ContractError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        return 1
    print(json.dumps({"userId": identity.user_id, "role": identity.role}))
    return 0


def cmd_auth_user_disable(auth_store: str, auth_dir: str, user_id: str) -> int:
    if auth_store not in ("demo", "iris"):
        print(json.dumps({"error": "auth store must be demo or iris"}))
        return 2
    target = Path(auth_dir)
    try:
        check_auth_dir(target)
        store = _store_for(auth_store, target)
        service = AuthService(
            store=store,
            keys=load_key_file(key_path_for(target)),
            provider=LocalPasswordProvider(),
        )
    except ContractError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        return 1
    try:
        service.disable_user(user_id)
    except ContractError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        return 1
    print(json.dumps({"disabled": True, "userId": user_id}))
    return 0
