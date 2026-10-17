from __future__ import annotations

import base64
import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from rakathon_backend.common.errors import ContractError

KEY_SIZE = 32
NONCE_SIZE = 12
SIZE_CAP = 8192


@dataclass(frozen=True, slots=True)
class UploadKeys:
    key: bytes


def _parent_ok(path: Path) -> None:
    try:
        st = path.parent.lstat()
    except OSError as exc:
        raise ContractError(code="not_configured", message="converter key unavailable") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise ContractError(code="not_configured", message="converter key unavailable")
    if (st.st_mode & 0o077) != 0:
        raise ContractError(code="not_configured", message="converter key unavailable")


def _stat_ok(path: Path) -> None:
    try:
        st = path.lstat()
    except OSError as exc:
        raise ContractError(code="not_configured", message="converter key unavailable") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ContractError(code="not_configured", message="converter key unavailable")
    if (st.st_mode & 0o777) != 0o600:
        raise ContractError(code="not_configured", message="converter key unavailable")
    if st.st_size <= 0 or st.st_size > SIZE_CAP:
        raise ContractError(code="not_configured", message="converter key unavailable")


def generate_key_file(path: Path) -> UploadKeys:
    _parent_ok(path)
    raw_key = secrets.token_bytes(KEY_SIZE)
    payload = {"schema_version": 1, "key": base64.b64encode(raw_key).decode("ascii")}
    raw = json.dumps(payload).encode("utf-8")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags, 0o600)
    except FileExistsError as exc:
        raise ContractError(code="already_exists", message="converter key exists") from exc
    except OSError as exc:
        raise ContractError(code="not_configured", message="converter key unavailable") from exc
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.chmod(str(path), 0o600)
    except OSError:
        pass
    return UploadKeys(key=raw_key)


def load_key_file(path: Path) -> UploadKeys:
    _parent_ok(path)
    _stat_ok(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise ContractError(code="not_configured", message="converter key unavailable") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
            raise ContractError(code="not_configured", message="converter key unavailable")
        if (st.st_mode & 0o777) != 0o600:
            raise ContractError(code="not_configured", message="converter key unavailable")
        if st.st_size <= 0 or st.st_size > SIZE_CAP:
            raise ContractError(code="not_configured", message="converter key unavailable")
        chunks: list[bytes] = []
        remaining = SIZE_CAP + 1
        while remaining > 0:
            piece = os.read(fd, min(4096, remaining))
            if not piece:
                break
            chunks.append(piece)
            remaining -= len(piece)
        raw = b"".join(chunks)
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError(code="not_configured", message="converter key unavailable") from exc
    finally:
        os.close(fd)
    if not raw or len(raw) > SIZE_CAP:
        raise ContractError(code="not_configured", message="converter key unavailable")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ContractError(code="not_configured", message="converter key unavailable") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ContractError(code="not_configured", message="converter key unavailable")
    try:
        key = base64.b64decode(str(data.get("key", "")), validate=True)
    except (ValueError, TypeError) as exc:
        raise ContractError(code="not_configured", message="converter key unavailable") from exc
    if len(key) != KEY_SIZE or set(data.keys()) != {"schema_version", "key"}:
        raise ContractError(code="not_configured", message="converter key unavailable")
    return UploadKeys(key=key)


def seal(key: bytes, aad: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    nonce = secrets.token_bytes(NONCE_SIZE)
    ct = AESGCM(key).encrypt(aad, plaintext, nonce)
    return (nonce, ct)


def open_sealed(key: bytes, aad: bytes, nonce: bytes, ct: bytes) -> bytes:
    if len(nonce) != NONCE_SIZE or not ct or len(ct) > 8 * 1024 * 1024:
        raise ContractError(code="store_unavailable", message="upload store unavailable")
    try:
        return AESGCM(key).decrypt(aad, bytes(ct), bytes(nonce))
    except Exception as exc:
        raise ContractError(code="store_unavailable", message="upload store unavailable") from exc
