from __future__ import annotations

import contextlib
import hashlib
import hmac
import re
import uuid
from dataclasses import dataclass

from rakathon_backend.b2.auth.keys import (
    KeySet,
    blind_index,
    csrf_for_token,
    encrypt_username,
    hash_token,
    new_session_token,
)
from rakathon_backend.b2.auth.models import (
    ACCOUNT_LIMIT,
    ACCOUNT_WINDOW,
    GLOBAL_LIMIT,
    GLOBAL_WINDOW,
    MAX_SESSIONS_PER_USER,
    SESSION_ABSOLUTE_TTL,
    SESSION_IDLE_TTL,
    AuditCallback,
    AuthFailed,
    Clock,
    LoginResult,
    RateLimited,
    SessionRecord,
    UserIdentity,
    UserRecord,
)
from rakathon_backend.b2.auth.normalize import (
    normalize_username,
    system_clock,
    validate_password,
    validate_role,
)
from rakathon_backend.b2.auth.protocol import PersistentAuthStore
from rakathon_backend.b7.provider import LocalPasswordProvider
from rakathon_backend.b7.resolve import resolve_session
from rakathon_backend.common.errors import ContractError

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_UUID_RE = re.compile(r"^[a-f0-9]{32}$")


def _check_token_format(token: object) -> str:
    if not isinstance(token, str) or _TOKEN_RE.fullmatch(token) is None:
        raise AuthFailed()
    return token


def _check_user_id_format(user_id: object) -> str:
    if not isinstance(user_id, str) or _UUID_RE.fullmatch(user_id) is None:
        raise ContractError(code="bad_payload", message="user invalid")
    return user_id


def _invalid_account_key(index_key: bytes, raw: object) -> str:
    if isinstance(raw, str):
        sample = raw[:128].encode("utf-8", errors="ignore")[:256]
        data = b"invalid-username-v1\x00" + sample
    else:
        data = b"invalid-username-v1\x00non-string"
    return hmac.new(index_key, data, hashlib.sha256).hexdigest()


@dataclass
class AuthService:
    store: PersistentAuthStore
    keys: KeySet
    provider: LocalPasswordProvider
    clock: Clock = system_clock
    audit: AuditCallback | None = None
    account_limit: int = ACCOUNT_LIMIT
    account_window: int = ACCOUNT_WINDOW
    global_limit: int = GLOBAL_LIMIT
    global_window: int = GLOBAL_WINDOW

    def _emit(self, event: str, user_id: str, status: str) -> None:
        if self.audit is None:
            return
        with contextlib.suppress(Exception):
            self.audit({"event": event, "user_id": user_id, "status": status})

    def provision_user(self, username: str, password: str, role: str) -> UserIdentity:
        normalized = normalize_username(username)
        validate_password(password)
        validated_role = validate_role(role)
        index = blind_index(self.keys.index_key, normalized)
        now = int(self.clock())
        user_id = uuid.uuid4().hex
        nonce, ct = encrypt_username(self.keys.aead_key, user_id, normalized)
        pwd_hash = self.provider.hash_password(password)
        record = UserRecord(
            user_id=user_id,
            username_index=index,
            password_hash=pwd_hash,
            enc_nonce=nonce,
            enc_ct=ct,
            key_id=self.keys.key_id,
            role=validated_role,
            active=True,
            auth_version=1,
            created_at=now,
            updated_at=now,
        )
        self.store.create_user(record)
        self._emit("provision", user_id, "ok")
        return UserIdentity(
            user_id=user_id, username=normalized, role=validated_role, auth_version=1
        )

    def disable_user(self, user_id: str) -> None:
        uid = _check_user_id_format(user_id)
        current = self.store.get_user_by_id(uid)
        if current is None:
            raise ContractError(code="not_found", message="user not found")
        now = int(self.clock())
        updated = UserRecord(
            user_id=current.user_id,
            username_index=current.username_index,
            password_hash=current.password_hash,
            enc_nonce=bytes(current.enc_nonce),
            enc_ct=bytes(current.enc_ct),
            key_id=current.key_id,
            role=current.role,
            active=False,
            auth_version=current.auth_version + 1,
            created_at=current.created_at,
            updated_at=now,
        )
        self.store.update_user(updated)
        self.store.revoke_user_sessions(uid)
        self._emit("disable", uid, "ok")

    def set_role(self, user_id: str, role: str) -> None:
        uid = _check_user_id_format(user_id)
        validated_role = validate_role(role)
        current = self.store.get_user_by_id(uid)
        if current is None:
            raise ContractError(code="not_found", message="user not found")
        now = int(self.clock())
        updated = UserRecord(
            user_id=current.user_id,
            username_index=current.username_index,
            password_hash=current.password_hash,
            enc_nonce=bytes(current.enc_nonce),
            enc_ct=bytes(current.enc_ct),
            key_id=current.key_id,
            role=validated_role,
            active=current.active,
            auth_version=current.auth_version + 1,
            created_at=current.created_at,
            updated_at=now,
        )
        self.store.update_user(updated)
        self.store.revoke_user_sessions(uid)
        self._emit("role_change", uid, "ok")

    def set_password(self, user_id: str, password: str) -> None:
        uid = _check_user_id_format(user_id)
        validate_password(password)
        current = self.store.get_user_by_id(uid)
        if current is None:
            raise ContractError(code="not_found", message="user not found")
        now = int(self.clock())
        updated = UserRecord(
            user_id=current.user_id,
            username_index=current.username_index,
            password_hash=self.provider.hash_password(password),
            enc_nonce=bytes(current.enc_nonce),
            enc_ct=bytes(current.enc_ct),
            key_id=current.key_id,
            role=current.role,
            active=current.active,
            auth_version=current.auth_version + 1,
            created_at=current.created_at,
            updated_at=now,
        )
        self.store.update_user(updated)
        self.store.revoke_user_sessions(uid)
        self._emit("password_change", uid, "ok")

    def role_for_user(self, user_id: str) -> str | None:
        try:
            uid = _check_user_id_format(user_id)
        except ContractError:
            return None
        try:
            current = self.store.get_user_by_id(uid)
        except ContractError:
            return None
        if current is None or not current.active:
            return None
        if current.role == "watchdog":
            return None
        return (
            current.role
            if current.role in ("admin", "coordinator", "clinician", "viewer")
            else None
        )

    def login(self, username: str, password: str) -> LoginResult:
        try:
            normalized = normalize_username(username)
        except ContractError:
            invalid = _invalid_account_key(self.keys.index_key, username)
            now_invalid = int(self.clock())
            self.store.rate_reserve(
                invalid,
                now_invalid,
                self.account_limit,
                self.account_window,
                self.global_limit,
                self.global_window,
            )
            if not self.provider.try_acquire():
                raise RateLimited()
            try:
                self.provider.dummy_verify()
                self._emit("login", "unknown", "failed")
                raise AuthFailed()
            finally:
                self.provider.release()
        if not isinstance(password, str) or not password:
            raise AuthFailed()
        index = blind_index(self.keys.index_key, normalized)
        now = int(self.clock())
        self.store.rate_reserve(
            index,
            now,
            self.account_limit,
            self.account_window,
            self.global_limit,
            self.global_window,
        )
        if not self.provider.try_acquire():
            raise RateLimited()
        try:
            record = self.store.get_user_by_index(index)
            if record is None or not record.active:
                self.provider.dummy_verify()
                self._emit("login", "unknown", "failed")
                raise AuthFailed()
            try:
                ok = self.provider.verify(record.password_hash, password)
            except ContractError:
                self.provider.dummy_verify()
                self._emit("login", record.user_id, "failed")
                raise AuthFailed()
            if not ok:
                self._emit("login", record.user_id, "failed")
                raise AuthFailed()
            if self.provider.needs_rehash(record.password_hash):
                refreshed = UserRecord(
                    user_id=record.user_id,
                    username_index=record.username_index,
                    password_hash=self.provider.hash_password(password),
                    enc_nonce=bytes(record.enc_nonce),
                    enc_ct=bytes(record.enc_ct),
                    key_id=record.key_id,
                    role=record.role,
                    active=record.active,
                    auth_version=record.auth_version,
                    created_at=record.created_at,
                    updated_at=now,
                )
                with contextlib.suppress(ContractError):
                    self.store.update_user(refreshed)
            token = new_session_token()
            digest = hash_token(token)
            created = now
            session = SessionRecord(
                token_hash=digest,
                user_id=record.user_id,
                auth_version=record.auth_version,
                role=record.role,
                created_at=created,
                last_seen=created,
                expires_at=created + SESSION_ABSOLUTE_TTL,
            )
            if self.store.count_user_sessions(record.user_id) >= MAX_SESSIONS_PER_USER:
                self.store.prune_user_sessions(record.user_id, MAX_SESSIONS_PER_USER - 1)
            self.store.create_session(session)
            identity = UserIdentity(
                user_id=record.user_id,
                username=normalized,
                role=record.role,
                auth_version=record.auth_version,
            )
            self._emit("login", record.user_id, "ok")
            return LoginResult(session_token=token, identity=identity)
        finally:
            self.provider.release()

    def resolve(self, session_token: str) -> UserIdentity:
        token = _check_token_format(session_token)
        now = int(self.clock())
        return resolve_session(self.store, self.keys, token, now)

    def logout(self, session_token: str) -> None:
        token = _check_token_format(session_token)
        digest = hash_token(token)
        self.store.delete_session(digest)

    def csrf_token(self, session_token: str) -> str:
        token = _check_token_format(session_token)
        digest = hash_token(token)
        session = self.store.get_session(digest)
        if session is None:
            raise AuthFailed()
        now = int(self.clock())
        if now >= session.expires_at or (now - session.last_seen) >= SESSION_IDLE_TTL:
            raise AuthFailed()
        record = self.store.get_user_by_id(session.user_id)
        if record is None or not record.active:
            raise AuthFailed()
        if record.auth_version != session.auth_version or record.role != session.role:
            raise AuthFailed()
        return csrf_for_token(self.keys.csrf_key, token)

    def __repr__(self) -> str:
        return "AuthService()"


AuthBlock = AuthService
