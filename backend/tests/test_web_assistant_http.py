from __future__ import annotations

import asyncio
import http.client
import json
import threading
from typing import Any

import pytest
from test_web_assistant import fixture_service
from test_web_http import request

from rakathon_backend.web.http import WebServer

ORIGIN = "http://10.0.0.103:5174"
HEADERS = {"Origin": ORIGIN, "Content-Type": "application/json"}


@pytest.fixture
async def server() -> Any:
    service, _, _ = fixture_service()
    instance = WebServer(
        "127.0.0.1", 0, service, asyncio.get_running_loop(), "test-key", frozenset({ORIGIN})
    )
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        await asyncio.to_thread(instance.shutdown)
        await asyncio.to_thread(instance.server_close)
        thread.join()


async def test_post_and_get_unchanged(server: WebServer) -> None:
    status, headers, body = await request(
        server,
        "POST",
        "/api/v1/assistant",
        HEADERS,
        b'{"role":"pacient","text":"Synthetic question"}',
    )
    assert status == 200 and json.loads(body)["sources"] == []
    assert headers["Cache-Control"] == "no-store"
    for path in ("session", "workspace", "cases/synthetic-1"):
        assert (await request(server, path=f"/api/v1/{path}"))[0] == 200
    status, headers, _ = await request(server, path="/api/v1/assistant")
    assert status == 405 and headers["Allow"] == "POST"


@pytest.mark.parametrize(
    "headers,body,status",
    [
        ({"Content-Type": "application/json"}, b"{}", 403),
        ({**HEADERS, "Origin": "null"}, b"{}", 403),
        ({**HEADERS, "Host": "evil.invalid"}, b"{}", 403),
        ({**HEADERS, "X-Rakathon-Proxy-Key": "bad"}, b"{}", 403),
        ({**HEADERS, "Forwarded": "host=evil"}, b"{}", 403),
        ({**HEADERS, "Content-Type": "text/plain"}, b"{}", 400),
        (HEADERS, b"", 400),
        (HEADERS, b"x" * 16385, 400),
        (HEADERS, b'{"role":"pacient","role":"mdt","text":"Q"}', 400),
        (HEADERS, b'{"role":"pacient","text":"Q","history":[]}', 400),
        (HEADERS, b'{"role":"pacient","text":NaN}', 400),
    ],
)
async def test_route_guard(
    server: WebServer, headers: dict[str, str], body: bytes, status: int
) -> None:
    assert (await request(server, "POST", "/api/v1/assistant", headers, body))[0] == status


async def test_duplicate_post_headers(server: WebServer) -> None:
    def send() -> list[int]:
        statuses = []
        for name in ("Content-Type", "Content-Length", "Origin"):
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_address[1], timeout=5
            )
            try:
                connection.putrequest("POST", "/api/v1/assistant")
                for key, value in {
                    **HEADERS,
                    "Content-Length": "2",
                    "X-Rakathon-Proxy-Key": "test-key",
                }.items():
                    connection.putheader(key, value)
                    if key == name:
                        connection.putheader(key, value)
                connection.endheaders(b"{}")
                response = connection.getresponse()
                statuses.append(response.status)
                response.read()
            finally:
                connection.close()
        return statuses

    assert await asyncio.to_thread(send) == [400, 400, 400]
