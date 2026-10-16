from __future__ import annotations

import contextlib

from rakathon_backend.b2.auth.keys import (
    KeySet,
    blind_index,
    decrypt_username,
    hash_token,
)
from rakathon_backend.b2.auth.models import (
    SESSION_IDLE_TTL,
    AuthFailed,
    SessionRecord,
    UserIdentity,
    UserRecord,
)
from rakathon_backend.b2.auth.protocol import PersistentAuthStore
from rakathon_backend.common.errors import ContractError

MAX_RESOLVE_RETRIES = 3


def _invalid(store: PersistentAuthStore, digest: str) -> None:
    with contextlib.suppress(Exception):
        store.delete_session(digest)


def _checked_session(
    store: PersistentAuthStore, keys: KeySet, record: UserRecord, session: SessionRecord
) -> UserIdentity:
    try:
        username = decrypt_username(
            keys.aead_key, record.user_id, bytes(record.enc_nonce), bytes(record.enc_ct)
        )
    except ContractError:
        raise AuthFailed()
    if blind_index(keys.index_key, username) != record.username_index:
        raise AuthFailed()
    return UserIdentity(
        user_id=record.user_id,
        username=username,
        role=record.role,
        auth_version=record.auth_version,
    )


def _revalidate(
    store: PersistentAuthStore,
    session: SessionRecord,
    record: UserRecord | None,
    now: int,
    digest: str,
) -> UserRecord:
    if now >= session.expires_at or (now - session.last_seen) >= SESSION_IDLE_TTL:
        _invalid(store, digest)
        raise AuthFailed()
    if record is None or not record.active:
        _invalid(store, digest)
        raise AuthFailed()
    if record.auth_version != session.auth_version or record.role != session.role:
        _invalid(store, digest)
        raise AuthFailed()
    return record


def resolve_session(
    store: PersistentAuthStore,
    keys: KeySet,
    token: str,
    now: int,
) -> UserIdentity:
    digest = hash_token(token)
    session = store.get_session(digest)
    if session is None:
        raise AuthFailed()
    live = _revalidate(store, session, store.get_user_by_id(session.user_id), now, digest)
    desired = max(session.last_seen, now)
    if desired == session.last_seen:
        return _checked_session(store, keys, live, session)
    moved = store.cas_last_seen(digest, session.last_seen, desired)
    if moved:
        return _checked_session(store, keys, live, session)
    for _ in range(MAX_RESOLVE_RETRIES):
        fresh = store.get_session(digest)
        if fresh is None:
            raise AuthFailed()
        if fresh.user_id != session.user_id:
            raise AuthFailed()
        valid = _revalidate(store, fresh, store.get_user_by_id(fresh.user_id), now, digest)
        if fresh.last_seen >= now:
            return _checked_session(store, keys, valid, fresh)
        target = max(fresh.last_seen, now)
        advanced = store.cas_last_seen(digest, fresh.last_seen, target)
        if advanced:
            return _checked_session(store, keys, valid, fresh)
    raise AuthFailed()
