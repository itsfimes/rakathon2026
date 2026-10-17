from __future__ import annotations

import http.client
import json
import os
import sys
from pathlib import Path

from rakathon_backend.common.errors import ContractError
from rakathon_backend.web.config import load_proxy_key

DEFAULT_PORT = "18765"
DEFAULT_PROXY_KEY_FILE = "/state/auth/proxy.key"
PORT_KEY = "RAKATHON_HTTP_PORT"
PROXY_KEY_FILE_KEY = "RAKATHON_HTTP_PROXY_KEY_FILE"
PROXY_HEADER = "x-rakathon-proxy-key"
BODY_LIMIT = 1048577


def proxy_path_from_env(env: dict[str, str]) -> Path:
    raw = env.get(PROXY_KEY_FILE_KEY)
    if raw is None:
        return Path(DEFAULT_PROXY_KEY_FILE)
    if not raw.strip():
        raise ValueError(PROXY_KEY_FILE_KEY + " must not be empty")
    return Path(raw.strip())


def port_from_env(env: dict[str, str]) -> int:
    raw = env.get(PORT_KEY)
    text = DEFAULT_PORT if raw is None else raw.strip()
    if not text:
        raise ValueError(PORT_KEY + " must not be empty")
    try:
        port = int(text)
    except ValueError:
        raise ValueError(PORT_KEY + " is invalid") from None
    if port < 1 or port > 65535:
        raise ValueError(PORT_KEY + " is invalid")
    return port


def check_liveness(port: int, proxy_key: str) -> bool:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(
            "GET",
            "/health",
            headers={
                "Host": "127.0.0.1:" + str(port),
                PROXY_HEADER: proxy_key,
                "Connection": "close",
            },
        )
        resp = conn.getresponse()
        body = resp.read(BODY_LIMIT)
        if resp.status != 200:
            return False
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return False
        if not isinstance(payload, dict):
            return False
        return payload.get("status") == "ok" and payload.get("scope") == "liveness"
    except (OSError, http.client.HTTPException, ValueError, TimeoutError):
        return False
    finally:
        try:
            conn.close()
        except OSError:
            pass


def check_once(env: dict[str, str]) -> bool:
    try:
        port = port_from_env(env)
        proxy_key = load_proxy_key(proxy_path_from_env(env))
    except (ValueError, ContractError, OSError):
        return False
    return check_liveness(port, proxy_key)


def main() -> int:
    ok = check_once(dict(os.environ))
    if not ok:
        sys.stdout.write(json.dumps({"healthy": False, "scope": "liveness"}) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
