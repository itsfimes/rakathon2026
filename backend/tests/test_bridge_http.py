from __future__ import annotations

import contextlib
import socket
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from rakathon_backend.b2.memory import MemoryStorage, StoredVector
from rakathon_backend.bridge.client import BridgeClientConfig, EncryptedBridgeStorage
from rakathon_backend.bridge.crypto import BridgeCrypto, generate_key_file, load_key
from rakathon_backend.bridge.server import build_server, start_in_thread
from rakathon_backend.common.errors import ContractError, TransportError


@contextlib.contextmanager
def _live(
    tmp_path: Path, store: MemoryStorage, mode: str = "mock"
) -> Iterator[tuple[str, Path, str]]:
    key_path = tmp_path / "bridge.key"
    generate_key_file(key_path)
    key_id = "test-key"
    server = build_server("127.0.0.1", 0, key_path, key_id, store, mode=mode)
    port = int(server.server_address[1])
    thread = start_in_thread(server)
    try:
        yield (f"http://127.0.0.1:{port}/rpc", key_path, key_id)
    finally:
        server.shutdown()
        thread.join(timeout=5.0)


def _storage(url: str, key_path: Path, key_id: str) -> EncryptedBridgeStorage:
    config = BridgeClientConfig(
        url=url, key_file=key_path, key_id=key_id, allow_insecure_loopback=True
    )
    return EncryptedBridgeStorage(config)


def test_missing_envelope_refused(tmp_path: Path) -> None:
    with _live(tmp_path, MemoryStorage()) as (url, _, _):
        response = httpx.post(url, json={})
        assert response.status_code == 400


def test_unknown_key_and_bad_token_refused(tmp_path: Path) -> None:
    with _live(tmp_path, MemoryStorage()) as (url, _, _):
        assert httpx.post(url, json={"keyId": "nope", "token": "x"}).status_code == 401
        assert httpx.post(url, json={"keyId": "test-key", "token": "aaa"}).status_code == 401


def test_only_post_rpc(tmp_path: Path) -> None:
    with _live(tmp_path, MemoryStorage()) as (url, _, _):
        assert httpx.get(url).status_code == 404
        assert httpx.post(url.replace("/rpc", "/nope"), json={}).status_code == 404


def test_missing_content_length_refused(tmp_path: Path) -> None:
    with _live(tmp_path, MemoryStorage()) as (url, _, _):
        host, _, port_text = url.replace("http://", "").partition(":")
        port = int(port_text.split("/")[0])
        sock = socket.create_connection((host, port), timeout=5.0)
        try:
            sock.sendall(b"POST /rpc HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            data = sock.recv(4096)
        finally:
            sock.close()
        assert b"400" in data.split(b"\r\n", 1)[0]


def test_oversized_refused(tmp_path: Path) -> None:
    with _live(tmp_path, MemoryStorage()) as (url, _, _):
        host, _, port_text = url.replace("http://", "").partition(":")
        port = int(port_text.split("/")[0])
        sock = socket.create_connection((host, port), timeout=5.0)
        try:
            sock.sendall(
                b"POST /rpc HTTP/1.1\r\nHost: x\r\nContent-Length: 2097152\r\n"
                b"Connection: close\r\n\r\n"
            )
            data = sock.recv(4096)
        finally:
            sock.close()
        assert b"413" in data.split(b"\r\n", 1)[0]


def test_no_redirect_followed(tmp_path: Path) -> None:
    key_path = tmp_path / "bridge.key"
    generate_key_file(key_path)

    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(307, headers={"location": "https://loop.example/rpc"})

    client = httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False
    )
    config = BridgeClientConfig(url="https://bridge.example/rpc", key_file=key_path, key_id="k1")
    store = EncryptedBridgeStorage(config, client=client)
    with pytest.raises(TransportError):
        store.tasks_read(None)


def test_url_policy_https_or_loopback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = {
        "RAKATHON_ALLOW_IRIS_EGRESS": "1",
        "RAKATHON_BRIDGE_KEY_FILE": str(tmp_path / "bridge.key"),
        "RAKATHON_BRIDGE_KEY_ID": "k1",
    }
    generate_key_file(tmp_path / "bridge.key")
    env = dict(base, RAKATHON_BRIDGE_URL="http://remote.example/rpc")
    with pytest.raises(ContractError):
        BridgeClientConfig.from_env(env)
    env = dict(base, RAKATHON_BRIDGE_URL="http://127.0.0.1:9/rpc")
    with pytest.raises(ContractError):
        BridgeClientConfig.from_env(env)
    BridgeClientConfig.from_env(env, allow_insecure_loopback=True)
    env = dict(base)
    with pytest.raises(ContractError):
        BridgeClientConfig.from_env(env)
    monkeypatch.delenv("RAKATHON_ALLOW_IRIS_EGRESS", raising=False)
    with pytest.raises(ContractError):
        BridgeClientConfig.from_env({})


def test_encrypted_roundtrip_over_loopback(tmp_path: Path) -> None:
    store: MemoryStorage = MemoryStorage()
    with _live(tmp_path, store) as (url, key_path, key_id):
        client = _storage(url, key_path, key_id)
        try:
            task = {
                "id": "t1",
                "ownerId": "nurse",
                "dueAt": "2030-01-01T00:00:00+00:00",
                "status": "OPEN",
                "requiredAckUserIds": ["nurse"],
                "acknowledgedBy": [],
                "patientRef": "Patient/p1",
                "version": 1,
            }
            assert client.tasks_write(task)["id"] == "t1"
            assert len(client.tasks_read(None)) == 1
            assert client.tasks_ack("t1", "nurse")["status"] == "ACKED"
            resource = {"resourceType": "Patient", "id": "p1", "name": [{"text": "Anon"}]}
            assert client.fhir_write(resource)["id"] == "p1"
            assert client.fhir_read("Patient", "p1") is not None
            assert client.fhir_read("Patient", "missing") is None
            found = client.fhir_search("Patient", {})
            assert len(found) == 1
            crypto = BridgeCrypto(key=load_key(key_path), key_id=key_id)
            rid, token = crypto.encrypt_request("health", {})
            raw = httpx.post(url, json={"keyId": key_id, "token": token}).json()
            result = crypto.decrypt_response(str(raw["token"]), rid, "health")
            assert result == {"status": "ok", "mode": "mock"}
        finally:
            client.close()


def test_transaction_atomic_over_bridge(tmp_path: Path) -> None:
    store = MemoryStorage()
    with _live(tmp_path, store) as (url, key_path, key_id):
        client = _storage(url, key_path, key_id)
        try:
            good = {
                "resourceType": "Bundle",
                "type": "transaction",
                "entry": [
                    {
                        "request": {"method": "POST", "url": "Patient/p9"},
                        "resource": {"resourceType": "Patient", "id": "p9"},
                    },
                    {
                        "request": {"method": "DELETE", "url": "Patient/p9"},
                        "resource": {"resourceType": "Patient", "id": "p9"},
                    },
                ],
            }
            with pytest.raises(ContractError):
                client.fhir_transaction(good)
            assert client.fhir_read("Patient", "p9") is None
        finally:
            client.close()


def test_vector_not_configured_maps(tmp_path: Path) -> None:
    with _live(tmp_path, MemoryStorage()) as (url, key_path, key_id):
        client = _storage(url, key_path, key_id)
        try:
            with pytest.raises(LookupError):
                client.vector_search("anonymized", "x", 5)
        finally:
            client.close()


def test_vector_seeded_roundtrip(tmp_path: Path) -> None:
    store = MemoryStorage()
    store.seed_synthetic_vector(StoredVector(vector_id="v1", text="synthetic note"))
    with _live(tmp_path, store) as (url, key_path, key_id):
        client = _storage(url, key_path, key_id)
        try:
            hits = client.vector_search("anonymized", "x", 5)
            assert len(hits) == 1
        finally:
            client.close()
