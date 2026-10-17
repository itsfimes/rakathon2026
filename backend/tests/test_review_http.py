from __future__ import annotations

import http.client
import io
import json
import threading
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from rakathon_backend.b2.auth.models import AuthFailed
from rakathon_backend.converter.model_draft import build_model_draft
from rakathon_backend.uploads.crypto import generate_key_file
from rakathon_backend.uploads.http import UploadRoutes
from rakathon_backend.uploads.review_http import ReviewUploadRoutes
from rakathon_backend.uploads.review_store import ReviewStore
from rakathon_backend.uploads.store import UploadStore
from rakathon_backend.uploads.worker import UploadWorker
from rakathon_backend.web.config import WebConfig
from rakathon_backend.web.router import AuthHTTPRouter, VerifiedIdentity
from rakathon_backend.web.server import build_server, serve_forever

PROXY = "K" * 43
ORIGIN = "http://127.0.0.1:5173"
CASE = "SYN-000001"
ALIAS = "model-p9"
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


def _bundle(obs: str = "o1") -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": {"resourceType": "Patient", "id": ALIAS},
                "request": {"method": "PUT", "url": "Patient/" + ALIAS},
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": obs,
                    "status": "final",
                    "code": {"text": "GLU"},
                    "subject": {"reference": "Patient/" + ALIAS},
                },
                "request": {"method": "PUT", "url": "Observation/" + obs},
            },
        ],
    }


def _receipt() -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction-response",
        "entry": [{"response": {"status": "201 Created", "location": "Observation/x/_history/1"}}],
    }


def _setup(
    tmp_path: Path, importer: Any, ready: bool = True
) -> tuple[ReviewUploadRoutes, UploadStore]:
    store_dir = tmp_path / "persist"
    store_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    keys = generate_key_file(store_dir / "store.key")
    store = UploadStore(store_dir, keys)
    worker = UploadWorker(store, secret_file=None, recipe_cache=store_dir / "recipes.json")
    base = UploadRoutes(
        store,
        worker,
        authorize=lambda u, a: True,
        case_access=lambda u, c: c == CASE,
        ai_available=lambda: False,
    )
    reviews = ReviewStore(store)
    allow_approve = {"doc1": True, "admin": True}
    wrapper = ReviewUploadRoutes(
        base,
        reviews,
        authorize_approve=lambda u: allow_approve.get(u, False),
        import_ready=lambda: ready,
        importer=importer,
    )
    return (wrapper, store)


def _job(store: UploadStore, body: bytes = b"review body SYN-000001 words") -> dict[str, Any]:
    job = store.enqueue("doc1", CASE, "n.txt", body)
    job_id = str(job["id"])
    sha = str(job["sha256"])
    draft = build_model_draft(json.dumps(_bundle()), sha, "p", "m")
    store.write_result_blob(job_id, "model-draft", json.dumps(draft).encode())
    store.finish(job_id, "complete")
    out = store.get(job_id)
    assert out is not None
    return out


def _router(wrapper: ReviewUploadRoutes) -> AuthHTTPRouter:
    router = AuthHTTPRouter(WebConfig.build(ORIGIN, True), PROXY, _login, _resolve, _csrf, _noop)
    router.set_upload_handler(
        lambda ident, method, path, headers, body: (
            wrapper.handle(ident.user_id, ident.role, method, path, headers, body) or (404, {}, {})
        )
    )
    return router


def _live(router: AuthHTTPRouter) -> Iterator[tuple[str, int]]:
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


def _call(
    host: str,
    port: int,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    conn = http.client.HTTPConnection(host, port, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        reply = conn.getresponse()
        return (reply.status, reply.read(), {k.lower(): v for k, v in reply.getheaders()})
    finally:
        conn.close()


def _auth(token: str) -> dict[str, str]:
    return {"X-Rakathon-Proxy-Key": PROXY, "Cookie": f"rakathon_session_loopback={token}"}


def _json(token: str) -> dict[str, str]:
    out = _auth(token)
    out.update({"Origin": ORIGIN, "X-CSRF-Token": _csrf(token), "Content-Type": "application/json"})
    return out


def test_review_get_draft_badges(tmp_path: Path) -> None:
    calls: list[str] = []

    def _importer(job_id: str, user_id: str, prepared: dict[str, Any]) -> dict[str, Any]:
        calls.append(job_id)
        return _receipt()

    wrapper, store = _setup(tmp_path, _importer)
    job = _job(store)
    job_id = str(job["id"])
    router = _router(wrapper)
    for host, port in _live(router):
        status, raw, _ = _call(host, port, "GET", f"/api/v1/uploads/{job_id}/review", _auth(DOC))
        assert status == 200
        payload: dict[str, Any] = json.loads(raw.decode())
        assert payload["version"] == 1
        assert payload["review"]["revision"] == 0
        assert payload["approvalEnabled"] is True
        assert payload["approvalReason"] is None
        status, raw, _ = _call(
            host, port, "GET", f"/api/v1/uploads/{job_id}/review/model", _auth(DOC)
        )
        assert status == 200
        assert "Observation" in (json.loads(raw.decode())["modelOutputText"] or "")
        status, raw, _ = _call(host, port, "GET", f"/api/v1/uploads/{job_id}", _auth(DOC))
        assert status == 200
        assert json.loads(raw.decode())["job"]["review"]["revision"] == 0
        status, raw, _ = _call(host, port, "GET", f"/api/v1/cases/{CASE}/uploads", _auth(DOC))
        assert status == 200
        assert json.loads(raw.decode())["jobs"][0]["review"]["state"] == "pending"
        body = json.dumps({"revision": 0, "candidateText": "not json"}).encode()
        status, raw, _ = _call(
            host, port, "POST", f"/api/v1/uploads/{job_id}/review/draft", _json(DOC), body
        )
        assert status == 200
        saved: dict[str, Any] = json.loads(raw.decode())["review"]
        assert saved["revision"] == 1
        assert saved["validation"]["valid"] is False
        bad = json.dumps({"revision": 1, "candidateText": "x", "extra": 1}).encode()
        status, _, _ = _call(
            host, port, "POST", f"/api/v1/uploads/{job_id}/review/draft", _json(DOC), bad
        )
        assert status == 422
        dup = b'{"revision": 1, "revision": 2, "candidateText": "x"}'
        status, _, _ = _call(
            host, port, "POST", f"/api/v1/uploads/{job_id}/review/draft", _json(DOC), dup
        )
        assert status == 422
        status, _, _ = _call(
            host,
            port,
            "POST",
            f"/api/v1/uploads/{job_id}/review/approve",
            _json(DOC),
            json.dumps({"revision": 1, "patientConfirmed": True}).encode(),
        )
        assert status == 422
        assert calls == []


def test_approve_success_stale_idempotent_guards(tmp_path: Path) -> None:
    calls: list[str] = []

    def _importer(job_id: str, user_id: str, prepared: dict[str, Any]) -> dict[str, Any]:
        calls.append(job_id)
        return _receipt()

    wrapper, store = _setup(tmp_path, _importer)
    job = _job(store)
    job_id = str(job["id"])
    router = _router(wrapper)
    for host, port in _live(router):
        ok = json.dumps({"revision": 0, "patientConfirmed": True}).encode()
        status, raw, _ = _call(
            host, port, "POST", f"/api/v1/uploads/{job_id}/review/approve", _json(DOC), ok
        )
        assert status == 200
        assert json.loads(raw.decode())["review"]["state"] == "imported"
        assert len(calls) == 1
        stale = json.dumps({"revision": 9, "patientConfirmed": True}).encode()
        status, raw, _ = _call(
            host, port, "POST", f"/api/v1/uploads/{job_id}/review/approve", _json(DOC), stale
        )
        assert status == 409
        assert "currentRevision" in json.loads(raw.decode())["error"]
        status, _, _ = _call(
            host, port, "POST", f"/api/v1/uploads/{job_id}/review/approve", _json(DOC), ok
        )
        assert status == 200
        assert len(calls) == 1
        status, _, _ = _call(host, port, "GET", f"/api/v1/uploads/{job_id}/review", _auth(ADMIN))
        assert status == 404
        status, _, _ = _call(
            host, port, "POST", f"/api/v1/uploads/{job_id}/review/approve", _json(VIEWER), ok
        )
        assert status == 403
        wrong = dict(_json(DOC))
        wrong["X-CSRF-Token"] = "bad"
        status, _, _ = _call(
            host, port, "POST", f"/api/v1/uploads/{job_id}/review/approve", wrong, ok
        )
        assert status == 403
        bad_origin = dict(_json(DOC))
        bad_origin["Origin"] = "http://127.0.0.1:9999"
        status, _, _ = _call(
            host, port, "POST", f"/api/v1/uploads/{job_id}/review/approve", bad_origin, ok
        )
        assert status == 403
        no_proxy = {"Cookie": f"rakathon_session_loopback={DOC}"}
        status, _, _ = _call(host, port, "GET", f"/api/v1/uploads/{job_id}/review", no_proxy)
        assert status == 401
        status, raw, headers = _call(
            host, port, "GET", f"/api/v1/uploads/{job_id}/export", _auth(DOC)
        )
        assert status == 200
        assert headers.get("content-type") == "application/zip"
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = set(zf.namelist())
            assert "original.bin" in names
            assert "review.json" in names
            assert "approved-bundle.json" in names
            assert "import-receipt.json" in names
            assert b"transaction-response" in zf.read("import-receipt.json")


def test_not_configured_timeout_caps(tmp_path: Path) -> None:
    def _boom(job_id: str, user_id: str, prepared: dict[str, Any]) -> dict[str, Any]:
        raise TimeoutError("slow iris")

    wrapper, store = _setup(tmp_path, _boom)
    job = _job(store)
    job_id = str(job["id"])
    router = _router(wrapper)
    for host, port in _live(router):
        ok = json.dumps({"revision": 0, "patientConfirmed": True}).encode()
        status, _, _ = _call(
            host, port, "POST", f"/api/v1/uploads/{job_id}/review/approve", _json(DOC), ok
        )
        assert status == 503
        status, raw, _ = _call(host, port, "GET", f"/api/v1/uploads/{job_id}/review", _auth(DOC))
        assert json.loads(raw.decode())["review"]["state"] == "import-uncertain"
        big_candidate = "x" * (100 * 1024)
        cap_job = _job(store, b"cap body SYN-000001 words")
        big = json.dumps({"revision": 0, "candidateText": big_candidate}).encode()
        status, _, _ = _call(
            host, port, "POST", f"/api/v1/uploads/{cap_job['id']}/review/draft", _json(DOC), big
        )
        assert status in (200, 422)
        other = dict(_json(DOC))
        other["Content-Type"] = "application/json"
        status, _, _ = _call(host, port, "POST", "/api/v1/assistant", other, b"y" * (17 * 1024))
        assert status == 413
        time.sleep(0.05)
    wrapper2, store2 = _setup(tmp_path / "second", lambda j, u, p: _receipt(), ready=False)
    job2 = _job(store2)
    router2 = _router(wrapper2)
    for host, port in _live(router2):
        status, raw, _ = _call(
            host, port, "GET", f"/api/v1/uploads/{job2['id']}/review", _auth(DOC)
        )
        assert json.loads(raw.decode())["approvalReason"] == "not_configured"
        ok2 = json.dumps({"revision": 0, "patientConfirmed": True}).encode()
        status, _, _ = _call(
            host, port, "POST", f"/api/v1/uploads/{job2['id']}/review/approve", _json(DOC), ok2
        )
        assert status == 503
