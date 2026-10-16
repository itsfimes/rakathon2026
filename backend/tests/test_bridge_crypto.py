from __future__ import annotations

import os
import stat
import time
from pathlib import Path

import pytest

from rakathon_backend.bridge.crypto import BridgeCrypto, generate_key_file, load_key
from rakathon_backend.bridge.protocol import check_arguments, check_operation, check_outer
from rakathon_backend.bridge.replay import ReplayCache
from rakathon_backend.common.errors import ContractError


def _crypto(tmp_path: Path, key_id: str = "k1", ttl: int = 60) -> BridgeCrypto:
    key_path = tmp_path / f"{key_id}.key"
    generate_key_file(key_path)
    return BridgeCrypto(key=load_key(key_path), key_id=key_id, ttl=ttl)


def test_key_file_exclusive_and_0600(tmp_path: Path) -> None:
    target = tmp_path / "bridge.key"
    generate_key_file(target)
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    with pytest.raises(OSError):
        generate_key_file(target)


def test_key_file_rejects_group_readable_and_symlink(tmp_path: Path) -> None:
    target = tmp_path / "bridge.key"
    generate_key_file(target)
    os.chmod(target, 0o640)
    with pytest.raises(ContractError):
        load_key(target)
    os.chmod(target, 0o600)
    link = tmp_path / "link.key"
    link.symlink_to(target)
    with pytest.raises(ContractError):
        load_key(link)


def test_roundtrip_request_response(tmp_path: Path) -> None:
    crypto = _crypto(tmp_path)
    request_id, token = crypto.encrypt_request("tasks.read", {"taskId": None})
    inner = crypto.decrypt_request(token)
    assert inner["requestId"] == request_id
    assert inner["operation"] == "tasks.read"
    reply = crypto.encrypt_response("tasks.read", request_id, {"tasks": []})
    assert crypto.decrypt_response(reply, request_id, "tasks.read") == {"tasks": []}


def test_ciphertext_hides_arguments(tmp_path: Path) -> None:
    crypto = _crypto(tmp_path)
    _, token = crypto.encrypt_request("fhir.write", {"note": "secret-marker-xyz"})
    assert "secret-marker-xyz" not in token
    outer = {"keyId": "k1", "token": token}
    assert "secret-marker-xyz" not in str(outer)


def test_tampered_token_rejected(tmp_path: Path) -> None:
    crypto = _crypto(tmp_path)
    _, token = crypto.encrypt_request("health", {})
    last = "A" if token[-1] != "A" else "B"
    with pytest.raises(ContractError):
        crypto.decrypt_request(token[:-1] + last)


def test_wrong_key_rejected(tmp_path: Path) -> None:
    first = _crypto(tmp_path, key_id="shared")
    other_path = tmp_path / "other.key"
    generate_key_file(other_path)
    second = BridgeCrypto(key=load_key(other_path), key_id="shared")
    _, token = first.encrypt_request("health", {})
    with pytest.raises(ContractError):
        second.decrypt_request(token)


def test_expired_token_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    crypto = _crypto(tmp_path)
    _, token = crypto.encrypt_request("health", {})
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 600.0)
    with pytest.raises(ContractError):
        crypto.decrypt_request(token)


def test_reflected_request_rejected(tmp_path: Path) -> None:
    crypto = _crypto(tmp_path)
    request_id, token = crypto.encrypt_request("health", {})
    with pytest.raises(ContractError):
        crypto.decrypt_response(token, request_id, "health")
    reply = crypto.encrypt_response("health", request_id, {"status": "ok"})
    with pytest.raises(ContractError):
        crypto.decrypt_request(reply)


def test_swapped_reply_rejected(tmp_path: Path) -> None:
    crypto = _crypto(tmp_path)
    first_id, _ = crypto.encrypt_request("health", {})
    second_id, _ = crypto.encrypt_request("health", {})
    reply = crypto.encrypt_response("health", first_id, {"status": "ok"})
    with pytest.raises(ContractError):
        crypto.decrypt_response(reply, second_id, "health")


def test_replay_same_request_rejected() -> None:
    cache = ReplayCache(max_entries=10, ttl_seconds=120.0)
    cache.check_and_store("k", "r1")
    with pytest.raises(ContractError) as excinfo:
        cache.check_and_store("k", "r1")
    assert excinfo.value.code == "replay"


def test_replay_full_cache_rejects_closed() -> None:
    cache = ReplayCache(max_entries=1, ttl_seconds=120.0)
    cache.check_and_store("k", "r1")
    with pytest.raises(ContractError) as excinfo:
        cache.check_and_store("k", "r2")
    assert excinfo.value.code == "replay_full"


def test_outer_shape_strict() -> None:
    with pytest.raises(ContractError):
        check_outer({})
    with pytest.raises(ContractError):
        check_outer({"keyId": "k", "token": "t", "extra": 1})
    with pytest.raises(ContractError):
        check_operation("sql.drop")
    with pytest.raises(ContractError):
        check_arguments("tasks.write", {"task": "nope"})


def test_protocol_rejects_absolute_urls_and_methods() -> None:
    absolute = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "request": {"method": "POST", "url": "https://evil.example/Patient"},
                "resource": {"resourceType": "Patient", "id": "p1"},
            }
        ],
    }
    with pytest.raises(ContractError):
        check_arguments("fhir.write", {"bundle": absolute})
    removed = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "request": {"method": "DELETE", "url": "Patient/p1"},
                "resource": {"resourceType": "Patient", "id": "p1"},
            }
        ],
    }
    with pytest.raises(ContractError):
        check_arguments("fhir.write", {"bundle": removed})
