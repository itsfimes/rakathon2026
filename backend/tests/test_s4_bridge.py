from __future__ import annotations

import contextlib
import json
import os
import socket
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.bridge.client import BridgeClientConfig, EncryptedBridgeStorage
from rakathon_backend.bridge.crypto import BridgeCrypto, generate_key_file, load_key
from rakathon_backend.bridge.protocol import BRIDGE_OPERATIONS, check_operation
from rakathon_backend.bridge.server import build_server, start_in_thread
from rakathon_backend.common.errors import ContractError, TransportError


@contextlib.contextmanager
def _live(
    tmp_path: Path,
    store: MemoryStorage,
    key_id: str,
    audit: Path | None = None,
    allowed: frozenset[str] | None = None,
    timeout: float = 10.0,
) -> Iterator[tuple[str, Path]]:
    key_path = tmp_path / f"{key_id}.key"
    generate_key_file(key_path)
    server = build_server(
        "127.0.0.1",
        0,
        key_path,
        key_id,
        store,
        allowed_users=allowed,
        audit_path=audit,
        request_timeout=timeout,
    )
    port = int(server.server_address[1])
    thread = start_in_thread(server)
    try:
        yield (f"http://127.0.0.1:{port}/rpc", key_path)
    finally:
        server.shutdown()
        thread.join(timeout=5.0)


def _storage(url: str, key_path: Path, key_id: str) -> EncryptedBridgeStorage:
    config = BridgeClientConfig(
        url=url, key_file=key_path, key_id=key_id, allow_insecure_loopback=True
    )
    return EncryptedBridgeStorage(config)


def _task(tid: str = "t1") -> dict[str, Any]:
    return {
        "id": tid,
        "ownerId": "nurse",
        "dueAt": "2030-01-01T00:00:00+00:00",
        "status": "OPEN",
        "requiredAckUserIds": ["nurse"],
        "acknowledgedBy": [],
        "patientRef": "Patient/p1",
        "version": 1,
    }


def test_two_servers_do_not_contaminate(tmp_path: Path) -> None:
    store_a = MemoryStorage()
    store_b = MemoryStorage()
    with (
        _live(tmp_path, store_a, "key-a") as (url_a, key_a),
        _live(tmp_path, store_b, "key-b") as (url_b, key_b),
    ):
        client_a = _storage(url_a, key_a, "key-a")
        client_b = _storage(url_b, key_b, "key-b")
        try:
            client_a.tasks_write(_task("shared-id"))
            assert len(client_a.tasks_read(None)) == 1
            assert client_b.tasks_read(None) == []
            with pytest.raises(TransportError):
                other = _storage(url_a, key_b, "key-b")
                try:
                    other.tasks_read(None)
                finally:
                    other.close()
        finally:
            client_a.close()
            client_b.close()


def test_schema_discover_not_remote() -> None:
    assert "schema.discover" not in BRIDGE_OPERATIONS
    with pytest.raises(ContractError):
        check_operation("schema.discover")


def test_schema_discover_live_refused(tmp_path: Path) -> None:
    with _live(tmp_path, MemoryStorage(), "key-s") as (url, key_path):
        crypto = BridgeCrypto(key=load_key(key_path), key_id="key-s")
        rid, token = crypto.encrypt_request("schema.discover", {"kind": "tables"})
        raw = httpx.post(url, json={"keyId": "key-s", "token": token}).json()
        with pytest.raises(ContractError):
            crypto.decrypt_response(str(raw["token"]), rid, "schema.discover")


def test_bridge_create_duplicate_rejected(tmp_path: Path) -> None:
    with _live(tmp_path, MemoryStorage(), "key-d") as (url, key_path):
        client = _storage(url, key_path, "key-d")
        try:
            client.tasks_create(_task("dup"))
            with pytest.raises(ContractError):
                client.tasks_create(_task("dup"))
        finally:
            client.close()


def test_bridge_ack_allowlist(tmp_path: Path) -> None:
    with _live(tmp_path, MemoryStorage(), "key-u", allowed=frozenset({"nurse"})) as (
        url,
        key_path,
    ):
        client = _storage(url, key_path, "key-u")
        try:
            client.tasks_write(_task("t-ack"))
            assert client.tasks_ack("t-ack", "nurse")["status"] == "ACKED"
            with pytest.raises(ContractError):
                client.tasks_ack("t-ack", "mallory")
        finally:
            client.close()


def test_bridge_audit_jsonl(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    with _live(tmp_path, MemoryStorage(), "key-g", audit=audit) as (url, key_path):
        client = _storage(url, key_path, "key-g")
        try:
            client.tasks_write(_task("t-audit"))
            client.tasks_ack("t-audit", "nurse")
        finally:
            client.close()
    mode = stat.S_IMODE(audit.stat().st_mode)
    assert mode & 0o077 == 0
    lines = audit.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert set(first) == {"timestamp", "requestId", "operation", "assertedActor", "status"}
    assert first["operation"] == "tasks.write" and first["status"] == "ok"
    assert "asserted by authenticated B2 service" in second["assertedActor"]
    assert "not independently verified" in second["assertedActor"]
    assert isinstance(first["timestamp"], float)


def test_stalled_body_times_out(tmp_path: Path) -> None:
    with _live(tmp_path, MemoryStorage(), "key-t", timeout=0.3) as (url, _):
        host, _, rest = url.replace("http://", "").partition(":")
        port = int(rest.split("/")[0])
        sock = socket.create_connection((host, port), timeout=5.0)
        try:
            sock.settimeout(5.0)
            sock.sendall(
                b"POST /rpc HTTP/1.1\r\nHost: x\r\nContent-Length: 5000\r\n"
                b"Connection: close\r\n\r\n"
            )
            data = sock.recv(4096)
        finally:
            sock.close()
        assert b"400" in data.split(b"\r\n", 1)[0]


def test_forged_bridge_create_rejected(tmp_path: Path) -> None:
    with _live(tmp_path, MemoryStorage(), "key-f") as (url, key_path):
        client = _storage(url, key_path, "key-f")
        try:
            forged = _task("t-forged")
            forged["status"] = "DONE"
            with pytest.raises(ContractError):
                client.tasks_write(forged)
            assert client.tasks_read(None) == []
        finally:
            client.close()


def test_audit_file_mode_private(tmp_path: Path) -> None:
    audit = tmp_path / "sub" / "audit.jsonl"
    with _live(tmp_path, MemoryStorage(), "key-m", audit=audit):
        pass
    assert os.getuid() == audit.stat().st_uid
    assert stat.S_IMODE(audit.stat().st_mode) & 0o077 == 0
