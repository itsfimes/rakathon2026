from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import SplitResult, urljoin, urlsplit

import httpx

from rakathon_backend.common.collection import ACTIVE_COLLECTION, MAX_COLLECTION, CollectionState
from rakathon_backend.common.errors import ContractError

PAGE_SIZE = 50
MAX_PAGES = 10
MAX_BODY = 1024 * 1024
MAX_AGGREGATE = 768 * 1024
COLLECTION_SECONDS = 6.0
PHASE_SECONDS = 0.5
IDENTITY = re.compile(r"[A-Za-z0-9.-]{1,64}")


def _error(state: CollectionState, reason: str) -> ContractError:
    return ContractError(
        code=reason, message="FHIR collection unavailable", metadata=state.metadata(reason)
    )


def _remaining(state: CollectionState, deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if state.cancelled.is_set() or remaining <= 0:
        raise _error(state, "deadline_exceeded")
    return min(PHASE_SECONDS, remaining)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("Invalid JSON constant")


def safe_next(base: str, current: str, link: Any, state: CollectionState) -> str:
    try:
        if (
            not isinstance(link, str)
            or not link
            or len(link) > 4096
            or any(ord(c) < 33 or ord(c) == 127 for c in link)
            or "\\" in link
            or "#" in link
        ):
            raise ValueError("URL")
        raw = urlsplit(link)
        if (
            "%" in raw.path
            or any(part in (".", "..") for part in raw.path.split("/"))
            or "//" in raw.path
        ):
            raise ValueError("Path")
        target = urljoin(current, link)
        expected, parsed = urlsplit(base), urlsplit(target)

        def port(p: SplitResult) -> int:
            return p.port or (443 if p.scheme == "https" else 80)

        if (parsed.scheme, parsed.hostname, port(parsed)) != (
            expected.scheme,
            expected.hostname,
            port(expected),
        ):
            raise ValueError("Origin")
        boundary = expected.path.rstrip("/")
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or not (parsed.path == boundary or parsed.path.startswith(boundary + "/"))
        ):
            raise ValueError("Boundary")
        return target
    except ValueError as exc:
        raise _error(state, "unsafe_paging_link") from exc


def _page(
    client: httpx.Client, url: str, state: CollectionState, deadline: float
) -> dict[str, Any]:
    timeout = _remaining(state, deadline)
    try:
        with client.stream(
            "GET",
            url,
            follow_redirects=False,
            timeout=httpx.Timeout(timeout),
            headers={"Accept-Encoding": "identity"},
        ) as response:
            _remaining(state, deadline)
            if response.status_code != 200:
                raise _error(
                    state, "auth_failed" if response.status_code in (401, 403) else "upstream_error"
                )
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise _error(state, "invalid_response")
            chunks = bytearray()
            for chunk in response.iter_bytes():
                _remaining(state, deadline)
                if len(chunks) + len(chunk) > MAX_BODY:
                    raise _error(state, "resource_limit")
                chunks.extend(chunk)
            _remaining(state, deadline)
            body = json.loads(
                chunks.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant
            )
    except httpx.TimeoutException as exc:
        raise _error(state, "deadline_exceeded") from exc
    except httpx.HTTPError as exc:
        raise _error(state, "upstream_error") from exc
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise _error(state, "invalid_response") from exc
    if (
        not isinstance(body, dict)
        or body.get("resourceType") != "Bundle"
        or body.get("type") != "searchset"
    ):
        raise _error(state, "invalid_response")
    state.pages += 1
    return body


def collect(
    client: httpx.Client, base: str, resource_type: str, path: str, params: dict[str, str]
) -> tuple[list[dict[str, Any]], int | None]:
    state = ACTIVE_COLLECTION.get() or CollectionState()
    deadline = time.monotonic() + COLLECTION_SECONDS
    initial = dict(params)
    initial["_count"] = str(PAGE_SIZE)
    url = str(client.build_request("GET", path, params=initial).url)
    url = safe_next(base, url, url, state)
    visited: set[str] = set()
    identities: set[str] = set()
    resources: list[dict[str, Any]] = []
    size = 2
    while True:
        _remaining(state, deadline)
        if url in visited:
            raise _error(state, "paging_cycle")
        if state.pages >= MAX_PAGES:
            raise _error(state, "resource_limit")
        visited.add(url)
        body = _page(client, url, state, deadline)
        if "total" in body:
            total = body["total"]
            if type(total) is not int or not 0 <= total <= 2**53 - 1:
                raise _error(state, "invalid_response")
            if state.total is not None and state.total != total:
                raise _error(state, "inconsistent_total")
            state.total = total
        entries = body.get("entry", [])
        if not isinstance(entries, list):
            raise _error(state, "invalid_response")
        for entry in entries:
            _remaining(state, deadline)
            state.encountered += 1
            if state.encountered > MAX_COLLECTION:
                raise _error(state, "resource_limit")
            if not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict):
                raise _error(state, "invalid_response")
            resource = entry["resource"]
            rid = resource.get("id")
            if (
                resource.get("resourceType") != resource_type
                or not isinstance(rid, str)
                or IDENTITY.fullmatch(rid) is None
            ):
                raise _error(state, "invalid_response")
            patient = params.get("patient") or params.get("subject")
            if patient is not None:
                refs = [resource[key] for key in ("subject", "patient") if key in resource]
                if not refs or any(
                    not isinstance(ref, dict) or ref.get("reference") != patient for ref in refs
                ):
                    raise _error(state, "invalid_response")
            if rid in identities:
                raise _error(state, "duplicate_resource")
            try:
                size += len(json.dumps(resource, ensure_ascii=True, allow_nan=False).encode()) + 1
            except (ValueError, RecursionError) as exc:
                raise _error(state, "invalid_response") from exc
            if size > MAX_AGGREGATE:
                raise _error(state, "resource_limit")
            identities.add(rid)
            resources.append(resource)
            state.received += 1
        links = body.get("link", [])
        if not isinstance(links, list) or any(not isinstance(link, dict) for link in links):
            raise _error(state, "invalid_response")
        next_links = [link.get("url") for link in links if link.get("relation") == "next"]
        if len(next_links) > 1:
            raise _error(state, "unsafe_paging_link")
        if not next_links:
            _remaining(state, deadline)
            return resources, state.total
        url = safe_next(base, url, next_links[0], state)
