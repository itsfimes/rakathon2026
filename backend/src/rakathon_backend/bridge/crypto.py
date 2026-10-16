from __future__ import annotations

import json
import os
import stat
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from rakathon_backend.common.errors import ContractError

PROTOCOL_VERSION = 1
DEFAULT_TTL = 60
MAX_INNER_BYTES = 512 * 1024
MAX_TOKEN_CHARS = 1024 * 1024


def generate_key_file(path: Path) -> Path:
    target = Path(path)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(target), flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(key + b"\n")
    except BaseException:
        try:
            target.unlink()
        except OSError:
            pass
        raise
    try:
        os.chmod(str(target), 0o600)
    except OSError:
        pass
    return target


def load_key(path: Path) -> bytes:
    target = Path(path)
    if target.is_symlink():
        raise ContractError(code="bad_key_file", message="key file must not be a symlink")
    try:
        info = target.stat()
    except OSError as exc:
        raise ContractError(code="bad_key_file", message="key file unreadable") from exc
    if info.st_uid != os.getuid():
        raise ContractError(code="bad_key_file", message="key file owner mismatch")
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077 != 0:
        raise ContractError(code="bad_key_file", message="key file must be 0600")
    try:
        raw = target.read_bytes().strip()
    except OSError as exc:
        raise ContractError(code="bad_key_file", message="key file unreadable") from exc
    if len(raw) > 256:
        raise ContractError(code="bad_key_file", message="key file malformed")
    try:
        Fernet(raw)
    except Exception as exc:
        raise ContractError(code="bad_key_file", message="key file malformed") from exc
    return raw


def _check_inner_shape(inner: Any) -> dict[str, Any]:
    if not isinstance(inner, dict):
        raise ContractError(code="bad_envelope", message="inner message invalid")
    for key in ("version", "keyId", "direction", "requestId", "operation"):
        if key not in inner:
            raise ContractError(code="bad_envelope", message="inner message invalid")
    if inner.get("version") != PROTOCOL_VERSION:
        raise ContractError(code="bad_envelope", message="unsupported protocol version")
    if not isinstance(inner.get("keyId"), str) or not inner["keyId"].strip():
        raise ContractError(code="bad_envelope", message="inner message invalid")
    if inner.get("direction") not in ("request", "response"):
        raise ContractError(code="bad_envelope", message="inner message invalid")
    if not isinstance(inner.get("requestId"), str) or not inner["requestId"].strip():
        raise ContractError(code="bad_envelope", message="inner message invalid")
    if not isinstance(inner.get("operation"), str) or not inner["operation"].strip():
        raise ContractError(code="bad_envelope", message="inner message invalid")
    return inner


@dataclass
class BridgeCrypto:
    key: bytes
    key_id: str
    ttl: int = DEFAULT_TTL

    def __post_init__(self) -> None:
        if not self.key_id or not self.key_id.strip():
            raise ContractError(code="bad_key_id", message="keyId is required")
        if self.ttl < 10 or self.ttl > 600:
            raise ValueError("ttl out of bounds")
        self._fernet = Fernet(self.key)

    def encrypt_request(self, operation: str, arguments: dict[str, Any]) -> tuple[str, str]:
        return self._seal("request", operation, arguments, None)

    def encrypt_response(self, operation: str, request_id: str, result: dict[str, Any]) -> str:
        _token, sealed = self._seal("response", operation, result, request_id)
        return sealed

    def encrypt_error(self, operation: str, request_id: str, code: str, message: str) -> str:
        inner: dict[str, Any] = {
            "version": PROTOCOL_VERSION,
            "keyId": self.key_id,
            "direction": "response",
            "requestId": request_id,
            "operation": operation,
            "error": {"code": code, "message": message},
        }
        raw = json.dumps(inner, separators=(",", ":")).encode("utf-8")
        return self._fernet.encrypt(raw).decode("ascii")

    def _seal(
        self,
        direction: str,
        operation: str,
        body: dict[str, Any],
        request_id: str | None,
    ) -> tuple[str, str]:
        rid = request_id or uuid.uuid4().hex
        inner: dict[str, Any] = {
            "version": PROTOCOL_VERSION,
            "keyId": self.key_id,
            "direction": direction,
            "requestId": rid,
            "operation": operation,
        }
        if direction == "request":
            inner["arguments"] = dict(body)
        else:
            inner["result"] = dict(body)
        raw = json.dumps(inner, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_INNER_BYTES:
            raise ContractError(code="too_large", message="inner message too large")
        token = self._fernet.encrypt(raw).decode("ascii")
        if len(token) > MAX_TOKEN_CHARS:
            raise ContractError(code="too_large", message="token too large")
        return (rid, token)

    def decrypt_request(self, token: str) -> dict[str, Any]:
        inner = self._open(token)
        if inner.get("direction") != "request":
            raise ContractError(code="bad_envelope", message="reflected message rejected")
        if inner.get("keyId") != self.key_id:
            raise ContractError(code="bad_envelope", message="unknown key")
        args = inner.get("arguments")
        if not isinstance(args, dict):
            raise ContractError(code="bad_envelope", message="arguments invalid")
        return inner

    def decrypt_response(self, token: str, request_id: str, operation: str) -> dict[str, Any]:
        inner = self._open(token)
        if inner.get("direction") != "response":
            raise ContractError(code="bad_envelope", message="reflected message rejected")
        if inner.get("keyId") != self.key_id:
            raise ContractError(code="bad_envelope", message="unknown key")
        if inner.get("requestId") != request_id:
            raise ContractError(code="bad_envelope", message="request id mismatch")
        if inner.get("operation") != operation:
            raise ContractError(code="bad_envelope", message="operation mismatch")
        if "error" in inner:
            err = inner["error"]
            if not isinstance(err, dict):
                raise ContractError(code="remote_error", message="bridge request failed")
            raise ContractError(
                code=str(err.get("code", "remote_error")),
                message=str(err.get("message", "bridge request failed")),
            )
        result = inner.get("result")
        if not isinstance(result, dict):
            raise ContractError(code="bad_envelope", message="result invalid")
        return result

    def _open(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_CHARS:
            raise ContractError(code="bad_envelope", message="token invalid")
        try:
            raw = self._fernet.decrypt(token.encode("ascii"), ttl=self.ttl)
        except InvalidToken as exc:
            raise ContractError(code="auth_failed", message="decryption failed") from exc
        except Exception as exc:
            raise ContractError(code="bad_envelope", message="token invalid") from exc
        if len(raw) > MAX_INNER_BYTES + 4096:
            raise ContractError(code="too_large", message="inner message too large")
        try:
            inner = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ContractError(code="bad_envelope", message="inner message invalid") from exc
        return _check_inner_shape(inner)


def now_seconds() -> float:
    return time.time()
