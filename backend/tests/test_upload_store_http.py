from __future__ import annotations

import hashlib
import http.client
import io
import json
import threading
import time
import urllib.parse
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from docx_samples import make_docx

from rakathon_backend.b2.auth.models import AuthFailed
from rakathon_backend.common.errors import ContractError
from rakathon_backend.uploads.crypto import generate_key_file
from rakathon_backend.uploads.http import UploadRoutes
from rakathon_backend.uploads.store import MAX_FILE_BYTES, UploadStore
from rakathon_backend.uploads.worker import UploadWorker
from rakathon_backend.web.config import WebConfig
from rakathon_backend.web.router import AuthHTTPRouter, VerifiedIdentity
from rakathon_backend.web.server import build_server, serve_forever

PROXY = "K" * 43
ORIGIN = "http://127.0.0.1:5173"
CASE = "SYN-000001"

DOC = "D" * 43
ADMIN = "A" * 43
VIEWER = "V" * 43
IDENTITIES = {
    DOC: VerifiedIdentity("doc1", "doc.user", "clinician", 1),
    ADMIN: VerifiedIdentity("admin", "admin", "admin", 1),
    VIEWER: VerifiedIdentity("viewer", "viewer", "viewer", 1),
}


def _resolve(token: str) -> VerifiedIdentity:
    ident = IDENTITIES.get(token)
    if ident is None:
        raise AuthFailed()
    return ident


def _csrf(token: str) -> str:
    return "csrf-" + token


def _noop(token: str) -> None:
    _ = token


def _login(u: str, p: str) -> tuple[str, VerifiedIdentity, str]:
    _ = (u, p)
    raise AuthFailed()


Runner = Callable[[Path, Path, bool], int]


def make_routes(tmp_path: Path, runner: Runner | None) -> tuple[UploadRoutes, UploadStore]:
    store_dir = tmp_path / "persist"
    store_dir.mkdir(mode=0o700)
    keys = generate_key_file(store_dir / "store.key")
    store = UploadStore(store_dir, keys)
    worker = UploadWorker(
        store, secret_file=None, recipe_cache=store_dir / "recipes.json", runner=runner
    )
    routes = UploadRoutes(
        store,
        worker,
        authorize=lambda u, a: True,
        case_access=lambda u, c: c == CASE,
        ai_available=lambda: False,
    )
    return (routes, store)


def make_router(routes: UploadRoutes) -> AuthHTTPRouter:
    router = AuthHTTPRouter(WebConfig.build(ORIGIN, True), PROXY, _login, _resolve, _csrf, _noop)
    router.set_upload_handler(
        lambda ident, method, path, headers, body: (
            routes.handle(ident.user_id, ident.role, method, path, headers, body) or (404, {}, {})
        )
    )
    return router


def live(router: AuthHTTPRouter) -> Iterator[tuple[str, int]]:
    server = build_server("127.0.0.1", 0, router)
    port = int(server.server_address[1])
    thread = threading.Thread(target=serve_forever, args=(server,), daemon=True)
    thread.start()
    try:
        yield ("127.0.0.1", port)
    finally:
        server.shutdown()
        thread.join(timeout=5.0)
        server.server_close()


def call(
    host: str,
    port: int,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection(host, port, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        reply = conn.getresponse()
        data = reply.read()
        return (reply.status, {k.lower(): v for k, v in reply.getheaders()}, data)
    finally:
        conn.close()


def up_headers(token: str, name: str) -> dict[str, str]:
    return {
        "X-Rakathon-Proxy-Key": PROXY,
        "Cookie": f"rakathon_session_loopback={token}",
        "Origin": ORIGIN,
        "X-CSRF-Token": _csrf(token),
        "Content-Type": "application/octet-stream",
        "X-Upload-Name": urllib.parse.quote(name, safe=""),
    }


def review_runner(src: Path, out: Path, allow_azure: bool) -> int:
    _ = allow_azure
    try:
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
    except OSError:
        sha = ""
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(
        json.dumps(
            {
                "status": "manual-review",
                "bundle": None,
                "issues": [{"code": "unknown_no_extract", "message": "no decoder"}],
                "evidence": [],
                "needsReview": True,
                "writeEligible": False,
                "persistence": "not-written",
                "model": {"providerId": "p", "model": "m", "present": False},
                "source": {"sha256": sha},
                "adaptive": {
                    "newFormat": True,
                    "recipeReuse": False,
                    "plannerMode": "fallback",
                    "attempts": ["planner_fallback:no-agent"],
                    "fingerprint": "fp",
                },
            }
        )
    )
    (out / "provenance.json").write_text(
        json.dumps({"sourceSha256": sha, "adaptive": {"plannerMode": "fallback"}})
    )
    return 0


def wait_status(host: str, port: int, token: str, job_id: str) -> dict[str, Any]:
    headers = {"X-Rakathon-Proxy-Key": PROXY, "Cookie": f"rakathon_session_loopback={token}"}
    for _ in range(100):
        status, _, raw = call(host, port, "GET", f"/api/v1/uploads/{job_id}", headers)
        assert status == 200
        payload: dict[str, Any] = json.loads(raw.decode())
        job: dict[str, Any] = payload["job"]
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_capabilities_disabled_without_store() -> None:
    routes = UploadRoutes(None, None)
    status, _, payload = routes.capabilities("clinician")
    assert status == 200
    assert payload["enabled"] is False
    assert payload["reason"] == "converter_disabled"


def test_doctor_allowed_viewer_denied_and_guards(tmp_path: Path) -> None:
    routes, _ = make_routes(tmp_path, review_runner)
    router = make_router(routes)
    body = b"synthetic upload content SYN-21 with words"
    for host, port in live(router):
        status, _, raw = call(
            host, port, "POST", f"/api/v1/cases/{CASE}/uploads", up_headers(DOC, "note.hl7"), body
        )
        assert status == 202
        job_id = json.loads(raw.decode())["job"]["id"]
        assert len(job_id) == 32
        status, _, _ = call(
            host, port, "POST", f"/api/v1/cases/{CASE}/uploads", up_headers(VIEWER, "n.hl7"), body
        )
        assert status == 403
        bad = up_headers(DOC, "n.hl7")
        bad["Content-Type"] = "application/json"
        status, _, _ = call(host, port, "POST", f"/api/v1/cases/{CASE}/uploads", bad, body)
        assert status == 400
        no_csrf = up_headers(DOC, "n.hl7")
        del no_csrf["X-CSRF-Token"]
        status, _, _ = call(host, port, "POST", f"/api/v1/cases/{CASE}/uploads", no_csrf, body)
        assert status == 403
        no_auth = {"X-Rakathon-Proxy-Key": PROXY}
        status, _, _ = call(host, port, "POST", f"/api/v1/cases/{CASE}/uploads", no_auth, body)
        assert status == 401
        big = up_headers(DOC, "big.bin")
        try:
            status, _, _ = call(
                host,
                port,
                "POST",
                f"/api/v1/cases/{CASE}/uploads",
                big,
                b"x" * (MAX_FILE_BYTES + 1),
            )
            assert status == 413
        except (BrokenPipeError, ConnectionResetError):
            pass
        _ = wait_status(host, port, DOC, job_id)


def test_original_sha_exact_download_export_on_fail(tmp_path: Path) -> None:
    routes, store = make_routes(tmp_path, review_runner)
    router = make_router(routes)
    body = b"original bytes SYN-22 exact content here"
    digest = hashlib.sha256(body).hexdigest()
    for host, port in live(router):
        status, _, raw = call(
            host, port, "POST", f"/api/v1/cases/{CASE}/uploads", up_headers(DOC, "clip.hl7"), body
        )
        assert status == 202
        payload = json.loads(raw.decode())["job"]
        assert payload["sha256"] == digest
        assert payload["sourceUrn"] == f"urn:sha256:{digest}"
        job = wait_status(host, port, DOC, payload["id"])
        assert job["status"] == "manual-review"
        headers = {"X-Rakathon-Proxy-Key": PROXY, "Cookie": f"rakathon_session_loopback={DOC}"}
        status, out, raw = call(
            host, port, "GET", f"/api/v1/uploads/{payload['id']}/original", headers
        )
        assert status == 200
        assert raw == body
        assert out.get("content-disposition", "").startswith("attachment")
        assert out.get("x-content-type-options") == "nosniff"
        status, out, blob = call(
            host, port, "GET", f"/api/v1/uploads/{payload['id']}/export", headers
        )
        assert status == 200
        assert out.get("content-type") == "application/zip"
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            assert zf.read("original.bin") == body
            assert b"manual-review" in zf.read("result.json")
        other = {"X-Rakathon-Proxy-Key": PROXY, "Cookie": f"rakathon_session_loopback={ADMIN}"}
        status, _, _ = call(host, port, "GET", f"/api/v1/uploads/{payload['id']}", other)
        assert status == 404
        status, _, raw = call(host, port, "GET", f"/api/v1/cases/{CASE}/uploads", headers)
        assert status == 200
        assert any(j["id"] == payload["id"] for j in json.loads(raw.decode())["jobs"])
    assert store.read_original(payload["id"]) == body


def test_store_restart_marks_interrupted(tmp_path: Path) -> None:
    store_dir = tmp_path / "p2"
    store_dir.mkdir(mode=0o700)
    keys = generate_key_file(store_dir / "store.key")
    store = UploadStore(store_dir, keys)
    job = store.enqueue("doc1", CASE, "a.hl7", b"synthetic restart bytes SYN-23 words")
    store.claim_next()
    running = store.get(job["id"])
    assert running is not None and running["status"] == "running"
    reopened = UploadStore(store_dir, keys)
    back = reopened.get(job["id"])
    assert back is not None and back["status"] == "interrupted"
    assert reopened.read_original(job["id"]) == b"synthetic restart bytes SYN-23 words"


def test_store_queue_limits_and_supported_docx(tmp_path: Path) -> None:
    store_dir = tmp_path / "p3"
    store_dir.mkdir(mode=0o700)
    keys = generate_key_file(store_dir / "store.key")
    store = UploadStore(store_dir, keys)
    raw = make_docx([("p", "synthetic docx line SYN-24")])
    job = store.enqueue("doc1", CASE, "r.docx", raw)
    assert job["detectedType"].startswith("zip/")
    store.enqueue("doc1", CASE, "f0.hl7", b"words SYN-25 number 0 readable")
    with pytest.raises(ContractError):
        store.enqueue("doc1", CASE, "extra.hl7", b"words overflow SYN-26")
    with pytest.raises(ContractError):
        store.enqueue("doc1", CASE, "big.bin", b"x" * (MAX_FILE_BYTES + 1))
