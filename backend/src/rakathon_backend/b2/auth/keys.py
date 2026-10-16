from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from rakathon_backend.common.errors import ContractError

KEY_SIZE = 32
NONCE_SIZE = 12
SIZE_CAP = 8192
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True, slots=True)
class KeySet:
    key_id: str
    aead_key: bytes = field(repr=False)
    index_key: bytes = field(repr=False)
    csrf_key: bytes = field(repr=False)


def _parent_ok(path: Path) -> None:
    parent = path.parent
    try:
        st = parent.lstat()
    except OSError as exc:
        raise ContractError(code="not_configured", message="auth key unavailable") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise ContractError(code="not_configured", message="auth key unavailable")
    try:
        if st.st_uid != os.geteuid():
            raise ContractError(code="not_configured", message="auth key unavailable")
    except AttributeError:
        pass
    if (st.st_mode & 0o077) != 0:
        raise ContractError(code="not_configured", message="auth key unavailable")


def _file_stat_ok(path: Path) -> os.stat_result:
    try:
        st = path.lstat()
    except OSError as exc:
        raise ContractError(code="not_configured", message="auth key unavailable") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ContractError(code="not_configured", message="auth key unavailable")
    try:
        if st.st_uid != os.geteuid():
            raise ContractError(code="not_configured", message="auth key unavailable")
    except AttributeError:
        pass
    if (st.st_mode & 0o777) != 0o600:
        raise ContractError(code="not_configured", message="auth key unavailable")
    if st.st_size <= 0 or st.st_size > SIZE_CAP:
        raise ContractError(code="not_configured", message="auth key unavailable")
    return st


def _parse_key_file(raw: bytes) -> KeySet:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ContractError(code="not_configured", message="auth key unavailable") from exc
    if not isinstance(data, dict):
        raise ContractError(code="not_configured", message="auth key unavailable")
    if data.get("schema_version") != 1:
        raise ContractError(code="not_configured", message="auth key unavailable")
    key_id = data.get("key_id")
    if not isinstance(key_id, str) or _KEY_ID_RE.fullmatch(key_id) is None:
        raise ContractError(code="not_configured", message="auth key unavailable")
    try:
        aead = base64.b64decode(str(data.get("aead_key", "")), validate=True)
        index = base64.b64decode(str(data.get("index_key", "")), validate=True)
        csrf = base64.b64decode(str(data.get("csrf_key", "")), validate=True)
    except (ValueError, TypeError) as exc:
        raise ContractError(code="not_configured", message="auth key unavailable") from exc
    if len(aead) != KEY_SIZE or len(index) != KEY_SIZE or len(csrf) != KEY_SIZE:
        raise ContractError(code="not_configured", message="auth key unavailable")
    if set(data.keys()) != {"schema_version", "key_id", "aead_key", "index_key", "csrf_key"}:
        raise ContractError(code="not_configured", message="auth key unavailable")
    return KeySet(key_id=key_id, aead_key=aead, index_key=index, csrf_key=csrf)


def generate_key_file(path: Path) -> KeySet:
    _parent_ok(path)
    payload = {
        "schema_version": 1,
        "key_id": secrets.token_hex(8),
        "aead_key": base64.b64encode(secrets.token_bytes(KEY_SIZE)).decode("ascii"),
        "index_key": base64.b64encode(secrets.token_bytes(KEY_SIZE)).decode("ascii"),
        "csrf_key": base64.b64encode(secrets.token_bytes(KEY_SIZE)).decode("ascii"),
    }
    raw = json.dumps(payload).encode("utf-8")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags, 0o600)
    except FileExistsError as exc:
        raise ContractError(code="already_exists", message="auth key exists") from exc
    except OSError as exc:
        raise ContractError(code="not_configured", message="auth key unavailable") from exc
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.chmod(str(path), 0o600)
    except OSError:
        pass
    return _parse_key_file(raw)


def load_key_file(path: Path) -> KeySet:
    _parent_ok(path)
    _file_stat_ok(path)
    try:
        with open(path, "rb") as handle:
            raw = handle.read(SIZE_CAP + 1)
    except OSError as exc:
        raise ContractError(code="not_configured", message="auth key unavailable") from exc
    if not raw or len(raw) > SIZE_CAP:
        raise ContractError(code="not_configured", message="auth key unavailable")
    return _parse_key_file(raw)


def blind_index(index_key: bytes, username: str) -> str:
    return hmac.new(index_key, username.encode("utf-8"), hashlib.sha256).hexdigest()


def _aad(user_id: str) -> bytes:
    return f"{user_id}:v1".encode()


def encrypt_username(aead_key: bytes, user_id: str, username: str) -> tuple[bytes, bytes]:
    nonce = secrets.token_bytes(NONCE_SIZE)
    ct = AESGCM(aead_key).encrypt(_aad(user_id), username.encode("utf-8"), nonce)
    return (nonce, ct)


def decrypt_username(aead_key: bytes, user_id: str, nonce: bytes, ct: bytes) -> str:
    if len(nonce) != NONCE_SIZE or not ct or len(ct) > 4096:
        raise ContractError(code="store_unavailable", message="auth store unavailable")
    try:
        raw = AESGCM(aead_key).decrypt(_aad(user_id), bytes(ct), bytes(nonce))
        return raw.decode("utf-8")
    except Exception as exc:
        raise ContractError(code="store_unavailable", message="auth store unavailable") from exc


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_for_token(csrf_key: bytes, token: str) -> str:
    return hmac.new(csrf_key, token.encode("utf-8"), hashlib.sha256).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)
