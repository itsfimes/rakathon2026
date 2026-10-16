from __future__ import annotations

import asyncio
import http.client
import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest
from test_web_service import CountStore, FakeClient, bundle

from rakathon_backend.runtime.application import BackendApp, fresh_tokens
from rakathon_backend.web.http import WebServer
from rakathon_backend.web.runtime import serve_app
from rakathon_backend.web.security import checked_origins, proxy_key
from rakathon_backend.web.service import WebService


async def request(
    server: WebServer,
    method: str = "GET",
    path: str = "/api/v1/session",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    def send() -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        try:
            connection.request(
                method,
                path,
                body=body,
                headers={"X-Rakathon-Proxy-Key": "test-key", **(headers or {})},
            )
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    return await asyncio.to_thread(send)


@pytest.fixture
async def server() -> Any:
    instance = WebServer(
        "127.0.0.1",
        0,
        WebService(FakeClient()),
        asyncio.get_running_loop(),
        "test-key",
        frozenset({"http://10.0.0.103:5174"}),
    )
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        await asyncio.to_thread(instance.shutdown)
        await asyncio.to_thread(instance.server_close)
        thread.join()


async def test_allowed_request_no_cors_no_store(server: WebServer) -> None:
    status, headers, body = await request(server, headers={"Origin": "http://10.0.0.103:5174"})
    assert status == 200 and b"single-user-development" in body
    assert headers["Cache-Control"] == "no-store"
    assert not any(key.lower().startswith("access-control") for key in headers)
    assert b"test-key" not in body


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.invalid"},
        {"Host": "127.0.0.1:1"},
        {"Origin": "null"},
        {"Origin": "http://10.0.0.103:5174.evil"},
        {"X-Rakathon-Proxy-Key": "wrong"},
        {"X-Forwarded-Host": "127.0.0.1"},
        {"Forwarded": "host=localhost"},
    ],
)
async def test_security_headers_rejected(server: WebServer, headers: dict[str, str]) -> None:
    status, response_headers, _ = await request(server, headers=headers)
    assert status == 403 and response_headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD", "CUSTOM"])
async def test_only_get(server: WebServer, method: str) -> None:
    status, headers, _ = await request(server, method=method)
    assert status == 405 and headers["Allow"] == "GET"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/workspace?",
        "/api/v1/workspace?user=admin",
        "/api/v1/cases/a%2Fb",
        "/api/v1/cases/" + "a" * 65,
        "/api/v1/cases/a/b",
    ],
)
async def test_query_and_invalid_id(server: WebServer, path: str) -> None:
    status, _, _ = await request(server, path=path)
    assert status == 400


@pytest.mark.parametrize(
    "headers,body",
    [({}, b"payload"), ({"Transfer-Encoding": "chunked"}, None), ({"Content-Length": "-1"}, None)],
)
async def test_body_rejected(
    server: WebServer, headers: dict[str, str], body: bytes | None
) -> None:
    status, _, _ = await request(server, headers=headers, body=body)
    assert status == 400


async def test_unknown_routes_and_cases(server: WebServer) -> None:
    assert (await request(server, path="/rpc"))[0] == 404
    assert (await request(server, path="/api/v1/cases/unknown"))[0] == 404


async def test_duplicate_headers_and_missing_key(server: WebServer) -> None:
    def send() -> list[int]:
        statuses = []
        for extra in (
            [],
            [("Host", "evil")],
            [("X-Rakathon-Proxy-Key", "test-key")],
            [("Origin", "http://10.0.0.103:5174")],
        ):
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_address[1], timeout=5
            )
            try:
                connection.putrequest("GET", "/api/v1/session")
                if extra:
                    connection.putheader("X-Rakathon-Proxy-Key", "test-key")
                    connection.putheader("Origin", "http://10.0.0.103:5174")
                    for key, value in extra:
                        connection.putheader(key, value)
                connection.endheaders()
                response = connection.getresponse()
                statuses.append(response.status)
                response.read()
            finally:
                connection.close()
        return statuses

    assert await asyncio.to_thread(send) == [403, 400, 400, 400]


async def test_request_and_response_size_limits(server: WebServer) -> None:
    assert (await request(server, path="/" + "x" * 2048))[0] == 400
    assert (await request(server, headers={"Large": "x" * 17000}))[0] == 400


async def test_final_response_cap_includes_assistant_preview(
    server: WebServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def oversized_case(patient_id: str) -> tuple[int, dict[str, Any]]:
        return 200, {"version": 1, "assistantPreview": {"synthetic": "x" * (1024 * 1024)}}

    monkeypatch.setattr(server.service, "case", oversized_case)
    status, headers, body = await request(server, path="/api/v1/cases/synthetic-1")
    assert status == 503 and headers["Cache-Control"] == "no-store"
    assert len(body) < 1024 and b"assistantPreview" not in body


async def test_oversized_json_integer_isolated_to_unavailable_section(server: WebServer) -> None:
    client = FakeClient()
    client.responses["Observation"] = bundle(
        [
            {
                "resourceType": "Observation",
                "id": "synthetic-overflow",
                "subject": {"reference": "Patient/synthetic-1"},
                "valueQuantity": {"value": json.loads("1" + "0" * 400)},
            }
        ]
    )
    client.responses["DiagnosticReport"] = bundle(
        [
            {
                "resourceType": "DiagnosticReport",
                "id": "synthetic-report",
                "subject": {"reference": "Patient/synthetic-1"},
            }
        ]
    )
    server.service = WebService(client)
    status, _, body = await request(server, path="/api/v1/cases/synthetic-1")
    sections = json.loads(body)["sections"]
    assert status == 200
    assert sections["observations"]["status"] == "unavailable"
    assert sections["observations"]["reason"] == "invalid_response"
    assert sections["observations"]["items"] == []
    assert all(sections[key]["status"] == "complete" for key in ("conditions", "documents"))
    assert sections["diagnosticReports"]["status"] == "complete"
    assert sections["diagnosticReports"]["items"][0]["id"] == "synthetic-report"


def test_worker_admission_is_bounded(server: WebServer) -> None:
    for _ in range(8):
        assert server.slots.acquire(blocking=False)
    assert not server.slots.acquire(blocking=False)
    for _ in range(8):
        server.slots.release()


def test_key_private_persistent_and_safe(tmp_path: Path) -> None:
    path = tmp_path / "proxy.key"
    first = proxy_key(path)
    assert len(first) == 43 and proxy_key(path) == first
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)
    with pytest.raises(ValueError):
        proxy_key(path)
    path.unlink()
    path.symlink_to(tmp_path / "missing")
    with pytest.raises(OSError):
        proxy_key(path)
    path.unlink()
    os.mkfifo(path, mode=0o600)
    with pytest.raises(ValueError):
        proxy_key(path)


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "http://localhost:5174/",
        "http://user@localhost:5174",
        "http://localhost:5174/path",
        "http://localhost:5174?x=1",
    ],
)
def test_origin_config_exact(origin: str) -> None:
    with pytest.raises(ValueError):
        checked_origins([origin])


async def test_normal_lifecycle_closes_http_store_sockets(tmp_path: Path) -> None:
    store = CountStore()
    app = BackendApp(tmp_path / "uds", fresh_tokens(), store=store, mode="iris-fhir")
    stop = asyncio.Event()
    stop.set()
    await serve_app(app, "127.0.0.1", 0, "key", frozenset(), stop)
    assert store.closed and not list((tmp_path / "uds").glob("*.sock"))
