from __future__ import annotations

import ipaddress
import os
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from rakathon_backend.bridge.crypto import BridgeCrypto, load_key
from rakathon_backend.bridge.protocol import check_operation
from rakathon_backend.common.errors import ContractError, TransportError
from rakathon_backend.common.fhir import check_bundle, check_resource

RPC_PATH = "/rpc"
MAX_RESPONSE_BYTES = 1024 * 1024 + 1024


def _is_loopback_host(host: str) -> bool:
    text = host.strip().lower().rstrip(".")
    if text in ("localhost",):
        return True
    try:
        addr = ipaddress.ip_address(text)
        return addr.is_loopback
    except ValueError:
        return False


def _validate_url(url: str, allow_insecure_loopback: bool) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        raise ContractError(code="bad_url", message="bridge url invalid") from exc
    if parsed.fragment or parsed.username or parsed.password:
        raise ContractError(code="bad_url", message="bridge url invalid")
    if not parsed.path.endswith(RPC_PATH):
        raise ContractError(code="bad_url", message="bridge url must end with /rpc")
    host = parsed.hostname or ""
    if parsed.scheme == "https":
        if not host:
            raise ContractError(code="bad_url", message="bridge url invalid")
        return url
    if parsed.scheme == "http" and allow_insecure_loopback and _is_loopback_host(host):
        port = parsed.port
        if port is None:
            raise ContractError(code="bad_url", message="loopback url needs port")
        return url
    raise ContractError(code="bad_url", message="bridge url must be https")


@dataclass(frozen=True)
class BridgeClientConfig:
    url: str
    key_file: Path
    key_id: str
    ttl: int = 60
    connect_timeout: float = 5.0
    read_timeout: float = 15.0
    allow_insecure_loopback: bool = False

    @staticmethod
    def from_env(
        env: dict[str, str] | None = None, allow_insecure_loopback: bool = False
    ) -> BridgeClientConfig:
        source = dict(os.environ) if env is None else dict(env)
        if source.get("RAKATHON_ALLOW_IRIS_EGRESS", "0").strip() != "1":
            raise ContractError(code="egress_denied", message="iris egress is not enabled")
        url = source.get("RAKATHON_BRIDGE_URL", "").strip()
        key_file = source.get("RAKATHON_BRIDGE_KEY_FILE", "").strip()
        key_id = source.get("RAKATHON_BRIDGE_KEY_ID", "").strip()
        if not url or not key_file or not key_id:
            raise ContractError(code="not_configured", message="bridge client is not configured")
        allow_raw = source.get("RAKATHON_BRIDGE_ALLOWLIST", "").strip()
        if allow_raw:
            allowed = [item.strip() for item in allow_raw.split(",") if item.strip()]
            if url not in allowed:
                raise ContractError(code="egress_denied", message="bridge url not allowlisted")
        ttl_raw = source.get("RAKATHON_BRIDGE_TTL", "60").strip() or "60"
        try:
            ttl = int(ttl_raw)
        except ValueError as exc:
            raise ContractError(code="not_configured", message="bridge ttl invalid") from exc
        if ttl < 10 or ttl > 600:
            raise ContractError(code="not_configured", message="bridge ttl out of bounds")
        _validate_url(url, allow_insecure_loopback)
        return BridgeClientConfig(
            url=url,
            key_file=Path(key_file),
            key_id=key_id,
            ttl=ttl,
            allow_insecure_loopback=allow_insecure_loopback,
        )


class EncryptedBridgeStorage:
    def __init__(
        self,
        config: BridgeClientConfig,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        _validate_url(config.url, config.allow_insecure_loopback)
        key = load_key(config.key_file)
        self._crypto = BridgeCrypto(key=key, key_id=config.key_id, ttl=config.ttl)
        if client is not None:
            self._client: httpx.Client | None = client
            self._owned = False
        else:
            timeout = httpx.Timeout(
                connect=config.connect_timeout, read=config.read_timeout, write=5.0, pool=5.0
            )
            self._client = httpx.Client(
                verify=True,
                trust_env=False,
                follow_redirects=False,
                timeout=timeout,
            )
            self._owned = True

    def close(self) -> None:
        if self._owned and self._client is not None:
            self._client.close()

    def _rpc(self, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
        check_operation(operation)
        request_id, token = self._crypto.encrypt_request(operation, arguments)
        assert self._client is not None
        try:
            response = self._client.post(
                self._config.url,
                json={"keyId": self._config.key_id, "token": token},
            )
        except ContractError:
            raise
        except Exception as exc:
            raise TransportError(code="bridge_unreachable", message="bridge unreachable") from exc
        if response.status_code != 200:
            raise TransportError(code="bridge_error", message="bridge request failed")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise TransportError(code="bridge_error", message="bridge response too large")
        try:
            outer = response.json()
        except Exception as exc:
            raise TransportError(code="bridge_error", message="bridge response invalid") from exc
        if not isinstance(outer, dict) or "token" not in outer:
            raise TransportError(code="bridge_error", message="bridge response invalid")
        reply_token = outer.get("token")
        if not isinstance(reply_token, str):
            raise TransportError(code="bridge_error", message="bridge response invalid")
        try:
            return self._crypto.decrypt_response(reply_token, request_id, operation)
        except ContractError:
            raise
        except Exception as exc:
            raise TransportError(code="bridge_error", message="bridge request failed") from exc

    def fhir_write(self, resource: dict[str, Any]) -> dict[str, Any]:
        check_resource(dict(resource))
        result = self._rpc("fhir.write", {"resource": dict(resource)})
        stored = result.get("resource")
        if not isinstance(stored, dict):
            raise TransportError(code="bridge_error", message="bridge request failed")
        return stored

    def fhir_transaction(self, bundle: dict[str, Any]) -> dict[str, Any]:
        check_bundle(dict(bundle))
        result = self._rpc("fhir.write", {"bundle": dict(bundle)})
        out = result.get("bundle")
        if not isinstance(out, dict):
            raise TransportError(code="bridge_error", message="bridge request failed")
        return out

    def fhir_read(self, resource_type: str, rid: str) -> dict[str, Any] | None:
        result = self._rpc("fhir.read", {"resourceType": resource_type, "id": rid})
        found = result.get("resource")
        if found is None:
            return None
        if not isinstance(found, dict):
            raise TransportError(code="bridge_error", message="bridge request failed")
        return found

    def fhir_search(self, resource_type: str, params: dict[str, str]) -> list[dict[str, Any]]:
        result = self._rpc("fhir.search", {"resourceType": resource_type, "params": dict(params)})
        items = result.get("resources", [])
        if not isinstance(items, list):
            raise TransportError(code="bridge_error", message="bridge request failed")
        return [dict(x) for x in items if isinstance(x, dict)]

    def tasks_create(self, task: dict[str, Any]) -> dict[str, Any]:
        result = self._rpc("tasks.write", {"task": dict(task)})
        stored = result.get("task")
        if not isinstance(stored, dict):
            raise TransportError(code="bridge_error", message="bridge request failed")
        return stored

    def tasks_write(self, task: dict[str, Any]) -> dict[str, Any]:
        result = self._rpc("tasks.write", {"task": dict(task)})
        stored = result.get("task")
        if not isinstance(stored, dict):
            raise TransportError(code="bridge_error", message="bridge request failed")
        return stored

    def tasks_read(self, task_id: str | None = None) -> list[dict[str, Any]]:
        args: dict[str, Any] = {"taskId": task_id}
        result = self._rpc("tasks.read", args)
        items = result.get("tasks", [])
        if not isinstance(items, list):
            raise TransportError(code="bridge_error", message="bridge request failed")
        return [dict(x) for x in items if isinstance(x, dict)]

    def tasks_ack(self, task_id: str, user_id: str) -> dict[str, Any]:
        result = self._rpc("tasks.ack", {"taskId": task_id, "userId": user_id})
        stored = result.get("task")
        if not isinstance(stored, dict):
            raise TransportError(code="bridge_error", message="bridge request failed")
        return stored

    def vector_search(self, channel: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        try:
            result = self._rpc(
                "vector.search", {"channel": channel, "query": query, "limit": limit}
            )
        except ContractError as exc:
            if exc.code == "not_configured":
                raise LookupError("not_configured") from exc
            raise
        hits = result.get("hits", [])
        if not isinstance(hits, list):
            raise TransportError(code="bridge_error", message="bridge request failed")
        return [dict(x) for x in hits if isinstance(x, dict)]

    def screening_import(self, rows: list[dict[str, Any]]) -> dict[str, int]:
        result = self._rpc("screening.import", {"rows": [dict(r) for r in rows]})
        out: dict[str, int] = {}
        for key in ("imported", "skipped", "total"):
            value = result.get(key)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TransportError(code="bridge_error", message="bridge request failed")
            out[key] = value
        return out

    def screening_query(
        self,
        filters: dict[str, str],
        projection: list[str] | None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        result = self._rpc(
            "screening.query",
            {
                "filters": dict(filters),
                "projection": list(projection) if projection is not None else None,
                "limit": limit,
                "offset": offset,
            },
        )
        rows = result.get("rows", [])
        if not isinstance(rows, list):
            raise TransportError(code="bridge_error", message="bridge request failed")
        return {"rows": [dict(x) for x in rows if isinstance(x, dict)], "count": len(rows)}
