from __future__ import annotations

import contextlib
import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rakathon_backend.b2.auth.normalize import normalize_username
from rakathon_backend.common.errors import ContractError
from rakathon_backend.web.config import clear_cookie_header

DEMO_ACCOUNT_IDS = ("koordinator", "lekar", "mdt", "pacient")
EXPECTED_ROLES: dict[str, str] = {
    "koordinator": "coordinator",
    "lekar": "clinician",
    "mdt": "clinician",
    "pacient": "viewer",
}
MAX_FILE_BYTES = 8192
MAX_PASSWORD_CHARS = 256


class DemoLoginConfig:
    __slots__ = ("_passwords", "_usernames")

    def __init__(self, usernames: dict[str, str], passwords: dict[str, str]) -> None:
        self._usernames = dict(usernames)
        self._passwords = dict(passwords)

    def __repr__(self) -> str:
        return "DemoLoginConfig()"

    def credentials_for(self, account: str) -> tuple[str, str] | None:
        if account not in self._usernames:
            return None
        return (self._usernames[account], self._passwords[account])

    def expected_for(self, account: str) -> tuple[str, str] | None:
        creds = self.credentials_for(account)
        if creds is None:
            return None
        return (creds[0], EXPECTED_ROLES[account])

    def view_for(self, username: str, role: str) -> str | None:
        for account in DEMO_ACCOUNT_IDS:
            if self._usernames.get(account) == username and EXPECTED_ROLES[account] == role:
                return account
        return None


def demo_account_ids(config: DemoLoginConfig | None) -> list[str] | None:
    if config is None:
        return None
    return list(DEMO_ACCOUNT_IDS)


def demo_view_for(config: DemoLoginConfig | None, username: str, role: str) -> str | None:
    if config is None:
        return None
    return config.view_for(username, role)


def auth_success_body(
    user_id: str,
    username: str,
    role: str,
    csrf: str,
    demo: DemoLoginConfig | None,
    *,
    authenticated: bool = True,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "authenticated": authenticated,
        "user": {"id": user_id, "username": username, "role": role},
        "csrfToken": csrf,
    }
    if demo is not None:
        body["demoAccounts"] = list(DEMO_ACCOUNT_IDS)
        view = demo.view_for(username, role)
        if view is not None:
            body["demoView"] = view
    return body


def anon_session_body(demo: DemoLoginConfig | None) -> dict[str, Any]:
    if demo is None:
        return {"authenticated": False}
    return {"authenticated": False, "demoAccounts": list(DEMO_ACCOUNT_IDS)}


def demo_account_from(payload: dict[str, Any]) -> str | None:
    if set(payload.keys()) != {"account"}:
        return None
    account = payload.get("account")
    if not isinstance(account, str) or account not in DEMO_ACCOUNT_IDS:
        return None
    return account


def demo_matches(demo: DemoLoginConfig, account: str, username: str, role: str) -> bool:
    expected = demo.expected_for(account)
    return expected is not None and username == expected[0] and role == expected[1]


def is_demo_username(demo: DemoLoginConfig | None, username: str) -> bool:
    if demo is None:
        return False
    for account in DEMO_ACCOUNT_IDS:
        creds = demo.credentials_for(account)
        if creds is not None and creds[0] == username:
            return True
    return False


def demo_fail_closed(demo: DemoLoginConfig | None, username: str, role: str) -> bool:
    if demo is None:
        return False
    if demo.view_for(username, role) is not None:
        return False
    return is_demo_username(demo, username)


def revoke_quietly(logout: Callable[[str], None], token: str) -> None:
    with contextlib.suppress(Exception):
        logout(token)


def stale_session_401(
    demo: DemoLoginConfig | None, cookie_name: str, secure: bool
) -> tuple[int, dict[str, str], dict[str, Any]]:
    if demo is None:
        return (401, {}, auth_safe_error("invalid_credentials"))
    body = anon_session_body(demo)
    body["error"] = "invalid_credentials"
    return (401, {"Set-Cookie": clear_cookie_header(cookie_name, secure)}, body)


def revoked_stale_session_401(
    logout: Callable[[str], None],
    token: str,
    demo: DemoLoginConfig | None,
    cookie_name: str,
    secure: bool,
) -> tuple[int, dict[str, str], dict[str, Any]]:
    revoke_quietly(logout, token)
    return stale_session_401(demo, cookie_name, secure)


def auth_safe_error(code: str) -> dict[str, Any]:
    return {"error": code}


def auth_default_deny(
    identity: Any, method: str, path: str, body: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    _ = (identity, method, path, body)
    return (503, {"error": "not_configured"})


def _check_private_parent(path: Path) -> None:
    try:
        info = path.parent.lstat()
    except OSError as exc:
        raise ContractError(code="not_configured", message="demo login unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ContractError(code="not_configured", message="demo login unavailable")
    try:
        owner = info.st_uid == os.geteuid()
    except AttributeError:
        owner = info.st_uid == os.getuid()
    if not owner or (info.st_mode & 0o077) != 0:
        raise ContractError(code="not_configured", message="demo login unavailable")


def _read_bounded(path: Path) -> bytes:
    if path.is_symlink():
        raise ContractError(code="not_configured", message="demo login unavailable")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise ContractError(code="not_configured", message="demo login unavailable") from exc
    try:
        try:
            info = os.fstat(fd)
        except OSError as exc:
            raise ContractError(code="not_configured", message="demo login unavailable") from exc
        if not stat.S_ISREG(info.st_mode):
            raise ContractError(code="not_configured", message="demo login unavailable")
        try:
            owned = info.st_uid == os.geteuid()
        except AttributeError:
            owned = info.st_uid == os.getuid()
        if not owned or stat.S_IMODE(info.st_mode) != 0o600:
            raise ContractError(code="not_configured", message="demo login unavailable")
        if info.st_size <= 0 or info.st_size > MAX_FILE_BYTES:
            raise ContractError(code="not_configured", message="demo login unavailable")
        chunks: list[bytes] = []
        remaining = MAX_FILE_BYTES + 1
        while remaining > 0:
            try:
                part = os.read(fd, remaining)
            except OSError as exc:
                raise ContractError(
                    code="not_configured", message="demo login unavailable"
                ) from exc
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
        raw = b"".join(chunks)
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise ContractError(code="not_configured", message="demo login unavailable")
    return raw


def _parse_strict(raw: bytes) -> tuple[dict[str, str], dict[str, str]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(code="not_configured", message="demo login unavailable") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ContractError(code="not_configured", message="demo login unavailable") from exc
    if not isinstance(data, dict) or set(data.keys()) != set(DEMO_ACCOUNT_IDS):
        raise ContractError(code="not_configured", message="demo login unavailable")
    usernames: dict[str, str] = {}
    passwords: dict[str, str] = {}
    for account in DEMO_ACCOUNT_IDS:
        entry = data[account]
        if not isinstance(entry, dict) or set(entry.keys()) != {"username", "password"}:
            raise ContractError(code="not_configured", message="demo login unavailable")
        uname = entry["username"]
        pwd = entry["password"]
        if (
            not isinstance(uname, str)
            or not isinstance(pwd, str)
            or not uname
            or not pwd
            or len(uname) > 128
            or len(pwd) > MAX_PASSWORD_CHARS
        ):
            raise ContractError(code="not_configured", message="demo login unavailable")
        try:
            normalized = normalize_username(uname)
        except ContractError as exc:
            raise ContractError(code="not_configured", message="demo login unavailable") from exc
        usernames[account] = normalized
        passwords[account] = pwd
    if len(set(usernames.values())) != len(DEMO_ACCOUNT_IDS):
        raise ContractError(code="not_configured", message="demo login unavailable")
    return (usernames, passwords)


def load_demo_login_file(path: str | Path) -> DemoLoginConfig:
    target = Path(str(path))
    if not str(path):
        raise ContractError(code="not_configured", message="demo login unavailable")
    _check_private_parent(target)
    raw = _read_bounded(target)
    usernames, passwords = _parse_strict(raw)
    return DemoLoginConfig(usernames, passwords)
