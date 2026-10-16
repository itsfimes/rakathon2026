from __future__ import annotations

import argparse
import base64
import http.server
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


def free_port(host: str) -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def start_fake_provider(port: int) -> http.server.ThreadingHTTPServer:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps({"data": [{"id": "tiny"}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", "0") or 0)
            if length:
                self.rfile.read(length)
            first = (
                'data: {"id":"chatcmpl-1","object":"chat.completion.chunk",'
                '"created":1,"model":"tiny","choices":[{"index":0,'
                '"delta":{"role":"assistant","content":"{\\"answer\\""},'
                '"finish_reason":null}]}\n\n'
            )
            second = (
                'data: {"id":"chatcmpl-1","object":"chat.completion.chunk",'
                '"created":1,"model":"tiny","choices":[{"index":0,'
                '"delta":{"content":": \\"hi\\"}"},"finish_reason":null}]}\n\n'
            )
            third = (
                'data: {"id":"chatcmpl-1","object":"chat.completion.chunk",'
                '"created":1,"model":"tiny","choices":[{"index":0,'
                '"delta":{},"finish_reason":"stop"}]}\n\n'
            )
            body = (first + second + third + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            _ = args

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def call(
    method: str,
    url: str,
    body: dict[str, object] | None,
    auth: str,
    timeout: float,
) -> tuple[str, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        request.add_header("content-type", "application/json")
    request.add_header("authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return (str(response.status), response.read()[:2000])
    except urllib.error.HTTPError as exc:
        return (str(exc.code), exc.read()[:2000])
    except OSError as exc:
        return ("ERR", f"{type(exc).__name__}: {exc}".encode()[:300])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default="opencode")
    parser.add_argument("--expected-version", default="2.0.31")
    parser.add_argument("--provider-id", default="loopro")
    parser.add_argument("--model", default="tiny")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    probe = subprocess.run(
        [args.binary, "--version"],
        check=False,
        capture_output=True,
        timeout=15,
        text=True,
    )
    version = probe.stdout.strip()
    print(f"VERSION rc={probe.returncode} out={version!r}", flush=True)
    if version != f"opencode v{args.expected_version}":
        print("VERSION_MISMATCH", flush=True)
        return 2
    provider_port = free_port("127.0.0.1")
    serve_port = free_port("127.0.0.1")
    fake = start_fake_provider(provider_port)
    scratch = Path(tempfile.mkdtemp(prefix="ai-smoke-", dir="/tmp/opencode"))
    password = secrets.token_urlsafe(32)
    config = {
        "provider": {
            args.provider_id: {
                "npm": "@ai-sdk/openai-compatible",
                "name": args.provider_id,
                "options": {"baseURL": f"http://127.0.0.1:{provider_port}"},
                "models": {args.model: {"name": args.model}},
            }
        },
        "permission": "deny",
        "model": f"{args.provider_id}/{args.model}",
    }
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": str(scratch),
        "XDG_CONFIG_HOME": str(scratch / "config"),
        "XDG_DATA_HOME": str(scratch / "data"),
        "XDG_STATE_HOME": str(scratch / "state"),
        "XDG_CACHE_HOME": str(scratch / "cache"),
        "TMPDIR": str(scratch / "tmp"),
        "OPENCODE_CONFIG_CONTENT": json.dumps(config),
        "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
        "OPENCODE_DB": ":memory:",
        "OPENCODE_SERVER_PASSWORD": password,
    }
    for sub in ("config", "data", "state", "cache", "tmp"):
        (scratch / sub).mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [args.binary, "serve", "--hostname=127.0.0.1", f"--port={serve_port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    base = f"http://127.0.0.1:{serve_port}"
    auth = f"opencode:{password}"
    failures = 0
    try:
        deadline = time.time() + args.timeout
        ready = False
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            status, _ = call("GET", base + "/api/session", None, auth, 3.0)
            if status == "200":
                ready = True
                break
            time.sleep(0.3)
        print(f"READY ready={ready} rc={proc.poll()}", flush=True)
        if not ready:
            return 1
        status, raw = call("GET", base + "/api/session", None, "opencode:wrong", 5.0)
        print(f"AUTH wrong-password -> {status}", flush=True)
        if status != "401":
            failures += 1
        payload: dict[str, object] = {
            "model": {"providerID": args.provider_id, "id": args.model},
            "permissions": [{"action": "*", "resource": "*", "effect": "deny"}],
        }
        status, raw = call("POST", base + "/api/session", payload, auth, 8.0)
        print(f"CREATE -> {status} {raw[:400]!r}", flush=True)
        if status != "200":
            failures += 1
            return 1
        try:
            session_id = str(json.loads(raw.decode())["data"]["id"])
        except (ValueError, KeyError, TypeError):
            print("CREATE_NO_ID", flush=True)
            return 1
        print(f"SESSION {session_id}", flush=True)
        status, raw = call(
            "POST",
            base + f"/api/session/{session_id}/generate",
            {"prompt": "say hi"},
            auth,
            30.0,
        )
        print(f"GENERATE -> {status} {raw[:600]!r}", flush=True)
        if status != "200":
            failures += 1
        status, raw = call(
            "POST",
            base + f"/api/session/{session_id}/interrupt?resume=false",
            None,
            auth,
            8.0,
        )
        print(f"INTERRUPT -> {status} {raw[:300]!r}", flush=True)
        if status != "200":
            failures += 1
        status, raw = call("DELETE", base + f"/api/session/{session_id}", None, auth, 8.0)
        print(f"DELETE -> {status} {raw[:300]!r}", flush=True)
        if status not in ("200", "204"):
            failures += 1
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
        shutil.rmtree(scratch, ignore_errors=True)
        fake.shutdown()
    print(f"SMOKE failures={failures}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
