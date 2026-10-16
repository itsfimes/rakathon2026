from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from rakathon_backend.b2.collection import read_collection
from rakathon_backend.b2.iris import pagination
from rakathon_backend.b2.iris.config import IrisFhirConfig
from rakathon_backend.b2.iris.fhir import DirectFhirAdapter
from rakathon_backend.common.errors import ContractError

BASE = "http://127.0.0.1:8765/fhir/r4"


def adapter(handler: Callable[[httpx.Request], httpx.Response]) -> DirectFhirAdapter:
    client = httpx.Client(
        base_url=BASE,
        auth=("synthetic", "key"),
        transport=httpx.MockTransport(handler),
        trust_env=False,
        follow_redirects=False,
    )
    return DirectFhirAdapter(IrisFhirConfig(BASE, "synthetic", "key"), client=client)


def observation(index: int) -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "id": f"obs-{index}",
        "subject": {"reference": "Patient/p"},
        "code": {"text": f"Synthetic test {index}"},
        "valueQuantity": {"value": 0, "unit": "test"},
    }


def page(
    items: list[dict[str, Any]], next_url: str | None = None, total: int | None = 88
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [{"resource": item} for item in items],
    }
    if next_url is not None:
        result["link"] = [{"relation": "next", "url": next_url}]
    if total is not None:
        result["total"] = total
    return result


@pytest.mark.parametrize("total", [None, 0, 88, 200])
def test_50_plus_38_preserves_opaque_query_and_optional_estimate(total: int | None) -> None:
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            assert request.url.params["_count"] == "50"
            return httpx.Response(
                200,
                json=page(
                    [observation(i) for i in range(50)], "?opaque=a%2Fb%2B%3D&cursor=x+y", total
                ),
            )
        assert request.url.query == b"opaque=a%2Fb%2B%3D&cursor=x+y"
        return httpx.Response(200, json=page([observation(i) for i in range(50, 88)], total=total))

    items, server_total = adapter(respond).search_with_total(
        "Observation", {"patient": "Patient/p"}
    )
    assert len(items) == 88 and len(calls) == 2 and server_total == total


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.invalid/fhir/r4",
        "http://127.0.0.1:1/fhir/r4",
        "/fhir/r4evil",
        "/other",
        "//evil.invalid/fhir/r4",
        "http://user@127.0.0.1:8765/fhir/r4",
        "?x=1#fragment",
        "../r4/Observation",
        "/fhir/r4/%2e%2e/secret",
        "/fhir/r4/a%2Fb",
        "/fhir/r4\\secret",
        "?x=\nprivate",
    ],
)
def test_unsafe_links_no_second_request_or_credentials(url: str) -> None:
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=page([observation(0)], url))

    with pytest.raises(ContractError) as failure:
        adapter(respond).search("Observation", {"patient": "Patient/p"})
    assert failure.value.code == "unsafe_paging_link" and len(calls) == 1
    assert failure.value.metadata["receivedCount"] == 1
    assert url not in str(failure.value)


@pytest.mark.parametrize(
    "variant,reason",
    [
        ("duplicate", "duplicate_resource"),
        ("wrongtype", "invalid_response"),
        ("wrongpatient", "invalid_response"),
        ("entry", "invalid_response"),
        ("total", "inconsistent_total"),
        ("cycle", "paging_cycle"),
        ("ambiguous", "unsafe_paging_link"),
    ],
)
def test_invalid_pages_fail_closed(variant: str, reason: str) -> None:
    count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if count == 1:
            body = page([observation(0)], "?page=2")
            if variant == "ambiguous":
                body["link"].append({"relation": "next", "url": "?page=3"})
            return httpx.Response(200, json=body)
        resource = observation(0 if variant == "duplicate" else 1)
        if variant == "wrongtype":
            resource["resourceType"] = "Patient"
        if variant == "wrongpatient":
            resource["subject"] = {"reference": "Patient/other"}
        body = page(
            [resource], "?page=2" if variant == "cycle" else None, 89 if variant == "total" else 88
        )
        if variant == "entry":
            body["entry"] = [{}]
        return httpx.Response(200, json=body)

    with pytest.raises(ContractError) as failure:
        adapter(respond).search("Observation", {"patient": "Patient/p"})
    assert failure.value.code == reason
    assert failure.value.metadata["receivedCount"] in (1, 2)


@pytest.mark.parametrize(
    "status,reason",
    [(401, "auth_failed"), (403, "auth_failed"), (500, "upstream_error"), (302, "upstream_error")],
)
def test_http_failure_safe(status: int, reason: str) -> None:
    with pytest.raises(ContractError) as failure:
        adapter(
            lambda r: httpx.Response(
                status, content=b"PRIVATE", headers={"Location": "https://evil.invalid"}
            )
        ).search("Observation", {})
    assert failure.value.code == reason and "PRIVATE" not in str(failure.value)


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b'{"resourceType":"Bundle","type":"searchset","entry":{},"total":88}',
        b'{"resourceType":"Bundle","resourceType":"Bundle","type":"searchset"}',
        b'{"resourceType":"Bundle","type":"searchset","total":NaN}',
    ],
)
def test_malformed_json_bundle(body: bytes) -> None:
    with pytest.raises(ContractError) as failure:
        adapter(lambda r: httpx.Response(200, content=body)).search("Observation", {})
    assert failure.value.code == "invalid_response"


@pytest.mark.parametrize("limit", ["pages", "entries", "aggregate", "body"])
def test_caps(limit: str) -> None:
    count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if limit == "body":
            return httpx.Response(200, content=b" " * (1024 * 1024 + 1))
        n = 501 if limit == "entries" else 1 if limit == "pages" else 50
        resources = [observation((count - 1) * n + i) for i in range(n)]
        if limit == "aggregate":
            for resource in resources:
                resource["valueString"] = "x" * 9000
        return httpx.Response(200, json=page(resources, f"?page={count + 1}", None))

    with pytest.raises(ContractError) as failure:
        adapter(respond).search("Observation", {})
    assert failure.value.code == "resource_limit"
    assert count <= 10 and failure.value.metadata["encounteredCount"] <= 501


def test_deadline_never_fetches_another_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pagination, "COLLECTION_SECONDS", 0.01)
    count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        time.sleep(0.02)
        return httpx.Response(200, json=page([observation(0)], "?page=2"))

    with pytest.raises(ContractError) as failure:
        adapter(respond).search("Observation", {})
    assert failure.value.code == "deadline_exceeded" and count == 1


def test_slow_small_chunks_are_checked_without_buffering(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pagination, "COLLECTION_SECONDS", 0.01)
    yielded = 0

    class SlowStream(httpx.SyncByteStream):
        def __iter__(self) -> Any:
            nonlocal yielded
            for _ in range(100):
                time.sleep(0.02)
                yielded += 1
                yield b" "

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Accept-Encoding"] == "identity"
        assert all(0 < value <= 0.01 for value in request.extensions["timeout"].values())
        return httpx.Response(200, stream=SlowStream())

    with pytest.raises(ContractError) as failure:
        adapter(respond).search("Observation", {})
    assert failure.value.code == "deadline_exceeded" and yielded == 1


def test_unexpected_compression_fails_before_decompression() -> None:
    with pytest.raises(ContractError) as failure:
        adapter(
            lambda r: httpx.Response(
                200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"private")
            )
        ).search("Observation", {})
    assert failure.value.code == "invalid_response"


def test_exact_entry_and_page_budgets_allow_terminal_complete() -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json=page(
                [observation(i) for i in range((calls - 1) * 50, calls * 50)],
                f"?page={calls + 1}" if calls < 10 else None,
                999,
            ),
        )

    items, total = adapter(respond).search_with_total("Observation", {})
    assert len(items) == 500 and calls == 10 and total == 999


async def test_cancel_signals_worker_no_next_page() -> None:
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        entered.set()
        assert release.wait(1)
        return httpx.Response(200, json=page([observation(0)], "?page=2"))

    fhir = adapter(respond)

    def run() -> Any:
        try:
            return fhir.search("Observation", {})
        finally:
            stopped.set()

    task = asyncio.create_task(read_collection(run))
    assert await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    assert await asyncio.to_thread(stopped.wait, 1)
    assert count == 1
