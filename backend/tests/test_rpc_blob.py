from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from rakathon_backend.common.blob_store import (
    BlobNotFound,
    BlobStore,
    BlobTooLarge,
    BlobUnsupportedType,
)
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import ContractError, TransportError
from rakathon_backend.common.framing import lookup_service
from rakathon_backend.common.ipc import UnixJsonClient, UnixJsonServer
from rakathon_backend.common.rpc import new_envelope, require_target


def _sock() -> Path:
    base = Path(tempfile.mkdtemp(prefix="raks", dir="/tmp/opencode"))
    return base / "t.sock"


async def _echo(request: Envelope) -> Envelope:
    return request.reply(
        source="b6", action="pong", payload={"ok": True}, data_kind=DataKind.METADATA
    )


def test_unicode_token_fails_safely() -> None:
    assert lookup_service({"tok": "b4"}, "žluťoučký") is None
    assert lookup_service({"tok": "b4"}, "") is None
    assert lookup_service({"tok": "b4"}, None) is None
    assert lookup_service({"tok": "b4"}, "tok") == "b4"


def test_require_target() -> None:
    tag = uuid.uuid4().hex
    env = Envelope(
        request_id=f"r-{tag}",
        correlation_id=f"c-{tag}",
        source="b4",
        target="b6",
        action="x",
        data_kind=DataKind.METADATA,
        payload={},
    )
    require_target(env, "b6")
    with pytest.raises(ContractError):
        require_target(env, "b2")


def test_blob_roundtrip_and_errors() -> None:
    store = BlobStore()
    ref = store.put(b'{"a": 1}', "application/json")
    assert ref.startswith("ipc-blob://b1/")
    record = store.get(ref)
    assert record.data == b'{"a": 1}'
    with pytest.raises(BlobUnsupportedType):
        store.put(b"%PDF", "application/pdf")
    with pytest.raises(BlobTooLarge):
        store.put(b"x" * (store.max_bytes + 1), "text/plain")
    with pytest.raises(BlobNotFound):
        store.get("ipc-blob://b1/deadbeef")
    with pytest.raises(BlobNotFound):
        store.get("/etc/passwd")


def test_envelope_ids_present() -> None:
    env = new_envelope(
        source="b4",
        target="b6",
        action="authorize",
        data_kind=DataKind.METADATA,
        payload={"userId": "viewer", "action": "tasks.read"},
    )
    assert env.request_id and env.correlation_id


async def test_target_mismatch_rejected_over_socket() -> None:
    path = _sock()
    server = UnixJsonServer(path, service_name="b6", token_registry={"t": "b4"}, handler=_echo)
    try:
        await server.start()
        client = UnixJsonClient(path, token="t", source="b4")
        tag = uuid.uuid4().hex
        bad = Envelope(
            request_id=f"r-{tag}",
            correlation_id=f"c-{tag}",
            source="b4",
            target="b9",
            action="x",
            data_kind=DataKind.METADATA,
            payload={},
        )
        with pytest.raises(TransportError):
            await client.call(bad, expect_source="b6")
    finally:
        await server.close()
        shutil.rmtree(path.parent, ignore_errors=True)


async def test_response_target_mismatch_rejected() -> None:
    async def bad_target(request: Envelope) -> Envelope:
        return Envelope(
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            source="b6",
            target="intruder",
            action="pong",
            data_kind=DataKind.METADATA,
            payload={},
        )

    path = _sock()
    server = UnixJsonServer(path, service_name="b6", token_registry={"t": "b4"}, handler=bad_target)
    try:
        await server.start()
        client = UnixJsonClient(path, token="t", source="b4")
        tag = uuid.uuid4().hex
        req = Envelope(
            request_id=f"r-{tag}",
            correlation_id=f"c-{tag}",
            source="b4",
            target="b6",
            action="x",
            data_kind=DataKind.METADATA,
            payload={},
        )
        with pytest.raises(TransportError):
            await client.call(req, expect_source="b6")
    finally:
        await server.close()
        shutil.rmtree(path.parent, ignore_errors=True)
