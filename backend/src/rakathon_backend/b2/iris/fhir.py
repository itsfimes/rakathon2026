from __future__ import annotations

import ipaddress
import json
import re
import urllib.parse
from typing import Any

import httpx

from rakathon_backend.b2.iris.config import TRUSTED_REMOTE_BASE, IrisFhirConfig
from rakathon_backend.common.errors import ContractError, TransportError
from rakathon_backend.common.fhir import ALLOWED_TYPES, check_bundle, check_resource

_ID_RE = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
_PARAM_KEY_RE = re.compile(r"^[A-Za-z0-9_\-.]{1,64}$")
MAX_BODY = 1024 * 1024


def _base_is_loopback(base: str) -> bool:
    try:
        host = urllib.parse.urlparse(base).hostname or ""
    except ValueError:
        return False
    try:
        return ipaddress.ip_address(host.strip()).is_loopback
    except ValueError:
        return False


class DirectFhirAdapter:
    def __init__(
        self,
        config: IrisFhirConfig,
        client: httpx.Client | None = None,
        trusted_remote: bool = False,
    ) -> None:
        remote = IrisFhirConfig._normalize_trusted_base(config.base_url) == TRUSTED_REMOTE_BASE
        if remote:
            if not (trusted_remote and config.trusted_remote):
                raise ContractError(code="not_configured", message="fhir is loopback only")
            if not config.verify_tls:
                raise ContractError(code="not_configured", message="remote needs tls verify")
            verify: bool = True
        elif _base_is_loopback(config.base_url):
            verify = config.verify_tls
        else:
            raise ContractError(code="not_configured", message="fhir is loopback only")
        self._config = config
        if client is not None:
            self._client = client
            self._owned = False
        else:
            timeout = httpx.Timeout(
                connect=config.connect_timeout, read=config.read_timeout, write=5.0, pool=5.0
            )
            self._client = httpx.Client(
                base_url=config.base_url,
                auth=(config.username, config.password),
                verify=verify,
                trust_env=False,
                follow_redirects=False,
                timeout=timeout,
                headers={"Accept": "application/fhir+json"},
            )
            self._owned = True

    def close(self) -> None:
        if self._owned:
            self._client.close()

    def _path(self, resource_type: str, rid: str | None = None) -> str:
        if resource_type not in ALLOWED_TYPES:
            raise ContractError(code="bad_payload", message="resourceType unsupported")
        if rid is not None and _ID_RE.fullmatch(rid) is None:
            raise ContractError(code="bad_payload", message="id invalid")
        if rid is None:
            return f"/{resource_type}"
        return f"/{resource_type}/{rid}"

    def _fail(self, response: httpx.Response) -> ContractError:
        text = ""
        try:
            text = response.text[:500]
        except (ValueError, LookupError, UnicodeError):
            text = ""
        if text.lstrip().startswith("<"):
            return ContractError(
                code="auth_failed" if response.status_code == 401 else "remote_error",
                message="iris request failed",
            )
        try:
            body = json.loads(text) if text else {}
        except ValueError:
            return ContractError(code="remote_error", message="iris request failed")
        if isinstance(body, dict) and body.get("resourceType") == "OperationOutcome":
            return ContractError(code="remote_error", message="iris request failed")
        return ContractError(code="remote_error", message="iris request failed")

    def read(self, resource_type: str, rid: str) -> dict[str, Any] | None:
        path = self._path(resource_type, rid)
        try:
            response = self._client.get(path)
        except Exception as exc:
            raise TransportError(code="bridge_error", message="iris unreachable") from exc
        if response.status_code == 404:
            return None
        if response.status_code in (401, 403):
            raise ContractError(code="auth_failed", message="iris request failed")
        if response.status_code != 200:
            raise self._fail(response)
        if len(response.content) > MAX_BODY:
            raise ContractError(code="remote_error", message="iris response too large")
        try:
            body = response.json()
        except Exception as exc:
            raise ContractError(code="remote_error", message="iris response invalid") from exc
        if not isinstance(body, dict) or body.get("resourceType") != resource_type:
            raise ContractError(code="remote_error", message="iris response invalid")
        return body

    def _clean_params(self, params: dict[str, str]) -> dict[str, str]:
        clean: dict[str, str] = {}
        for key, value in params.items():
            if _PARAM_KEY_RE.fullmatch(key) is None:
                raise ContractError(code="bad_payload", message="search param invalid")
            if not isinstance(value, str) or not value or len(value) > 256:
                raise ContractError(code="bad_payload", message="search param invalid")
            if "://" in value or value.startswith("//"):
                raise ContractError(code="bad_payload", message="search param invalid")
            clean[key] = value
        return clean

    def _parse_total(self, body: dict[str, Any]) -> int | None:
        if "total" not in body:
            return None
        total = body.get("total")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ContractError(code="remote_error", message="iris response invalid")
        return total

    def _fetch_bundle(
        self, resource_type: str, params: dict[str, str]
    ) -> tuple[list[dict[str, Any]], int | None]:
        path = self._path(resource_type)
        clean = self._clean_params(params)
        try:
            response = self._client.get(path, params=clean)
        except Exception as exc:
            raise TransportError(code="bridge_error", message="iris unreachable") from exc
        if response.status_code == 301 or response.status_code in (302, 303, 307, 308):
            raise ContractError(code="remote_error", message="iris redirect refused")
        if response.status_code in (401, 403):
            raise ContractError(code="auth_failed", message="iris request failed")
        if response.status_code != 200:
            raise self._fail(response)
        if len(response.content) > MAX_BODY:
            raise ContractError(code="remote_error", message="iris response too large")
        try:
            body = response.json()
        except Exception as exc:
            raise ContractError(code="remote_error", message="iris response invalid") from exc
        if not isinstance(body, dict) or body.get("resourceType") != "Bundle":
            raise ContractError(code="remote_error", message="iris response invalid")
        server_total = self._parse_total(body)
        for link in body.get("link", []) if isinstance(body.get("link"), list) else []:
            if isinstance(link, dict) and link.get("relation") == "next":
                raise ContractError(code="truncated", message="paged results truncated")
        out: list[dict[str, Any]] = []
        entries = body.get("entry", [])
        if not isinstance(entries, list):
            raise ContractError(code="remote_error", message="iris response invalid")
        for item in entries:
            if isinstance(item, dict) and isinstance(item.get("resource"), dict):
                out.append(dict(item["resource"]))
        return (out, server_total)

    def search(self, resource_type: str, params: dict[str, str]) -> list[dict[str, Any]]:
        items, _ = self._fetch_bundle(resource_type, params)
        return items

    def search_with_total(
        self, resource_type: str, params: dict[str, str]
    ) -> tuple[list[dict[str, Any]], int | None]:
        return self._fetch_bundle(resource_type, dict(params))

    def write(self, resource: dict[str, Any]) -> dict[str, Any]:
        check_resource(dict(resource))
        rtype = resource.get("resourceType")
        rid = resource.get("id")
        if not isinstance(rtype, str) or rtype not in ALLOWED_TYPES:
            raise ContractError(code="bad_payload", message="resourceType unsupported")
        if not isinstance(rid, str) or _ID_RE.fullmatch(rid.strip()) is None:
            raise ContractError(code="bad_payload", message="id invalid")
        payload = json.dumps(dict(resource)).encode("utf-8")
        if len(payload) > MAX_BODY:
            raise ContractError(code="too_large", message="resource too large")
        try:
            response = self._client.put(
                self._path(rtype, rid.strip()),
                content=payload,
                headers={"Content-Type": "application/fhir+json"},
            )
        except Exception as exc:
            raise TransportError(code="bridge_error", message="iris unreachable") from exc
        if response.status_code in (401, 403):
            raise ContractError(code="auth_failed", message="iris request failed")
        if response.status_code not in (200, 201):
            raise self._fail(response)
        try:
            body = response.json()
        except ValueError:
            return dict(resource)
        return body if isinstance(body, dict) else dict(resource)

    def transaction(self, bundle: dict[str, Any]) -> dict[str, Any]:
        check_bundle(dict(bundle))
        if bundle.get("resourceType") != "Bundle" or bundle.get("type") != "transaction":
            raise ContractError(code="bad_payload", message="Bundle must be transaction")
        entries = bundle.get("entry")
        if not isinstance(entries, list) or not entries:
            raise ContractError(code="bad_payload", message="transaction needs entries")
        payload = json.dumps(bundle).encode("utf-8")
        if len(payload) > MAX_BODY:
            raise ContractError(code="too_large", message="transaction too large")
        try:
            response = self._client.post(
                "/",
                content=payload,
                headers={"Content-Type": "application/fhir+json"},
            )
        except Exception as exc:
            raise TransportError(code="bridge_error", message="iris unreachable") from exc
        if response.status_code in (401, 403):
            raise ContractError(code="auth_failed", message="iris request failed")
        if response.status_code not in (200, 201):
            raise self._fail(response)
        try:
            body = response.json()
        except Exception as exc:
            raise ContractError(code="remote_error", message="iris response invalid") from exc
        if not isinstance(body, dict) or body.get("resourceType") != "Bundle":
            raise ContractError(code="remote_error", message="iris response invalid")
        for item in body.get("entry", []) if isinstance(body.get("entry"), list) else []:
            if not isinstance(item, dict):
                continue
            resp = item.get("response", {})
            status = resp.get("status", "") if isinstance(resp, dict) else ""
            if isinstance(status, str) and status[:1] in ("4", "5"):
                raise ContractError(code="remote_error", message="transaction entry failed")
            outcome = item.get("resource", {})
            if isinstance(outcome, dict) and outcome.get("resourceType") == "OperationOutcome":
                for issue in (
                    outcome.get("issue", []) if isinstance(outcome.get("issue"), list) else []
                ):
                    sev = issue.get("severity", "") if isinstance(issue, dict) else ""
                    if sev in ("error", "fatal"):
                        raise ContractError(code="remote_error", message="transaction entry failed")
        return body
