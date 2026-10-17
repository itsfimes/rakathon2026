from __future__ import annotations

import json
import os
import sys
from typing import NoReturn

DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = "18765"
DEFAULT_ORIGIN = "http://localhost:5173"
DEFAULT_AUTH_DIR = "/state/auth"
DEFAULT_RUNTIME_DIR = "/run/rakathon"
DEFAULT_IRIS_ENV_FILE = "/run/secrets/iris.env"
DEFAULT_AUTH_STORE = "demo"
DEFAULT_STORAGE = "iris-fhir"
PORT_KEY = "RAKATHON_HTTP_PORT"
ORIGIN_KEY = "RAKATHON_HTTP_ORIGIN"
AUTH_DIR_KEY = "RAKATHON_HTTP_AUTH_DIR"
RUNTIME_DIR_KEY = "RAKATHON_HTTP_RUNTIME_DIR"
IRIS_ENV_KEY = "RAKATHON_HTTP_IRIS_ENV_FILE"
CLI_NAME = "rakathon-backend"


def value_or_default(env: dict[str, str], key: str, default: str) -> str:
    raw = env.get(key)
    if raw is None:
        return default
    text = raw.strip()
    if not text:
        raise ValueError(key + " must not be empty")
    return text


def port_or_default(env: dict[str, str]) -> str:
    text = value_or_default(env, PORT_KEY, DEFAULT_PORT)
    try:
        port = int(text)
    except ValueError:
        raise ValueError(PORT_KEY + " is invalid") from None
    if port < 1 or port > 65535:
        raise ValueError(PORT_KEY + " is invalid")
    return str(port)


def build_default_argv(env: dict[str, str]) -> list[str]:
    port = port_or_default(env)
    origin = value_or_default(env, ORIGIN_KEY, DEFAULT_ORIGIN)
    auth_dir = value_or_default(env, AUTH_DIR_KEY, DEFAULT_AUTH_DIR)
    runtime_dir = value_or_default(env, RUNTIME_DIR_KEY, DEFAULT_RUNTIME_DIR)
    iris_env = value_or_default(env, IRIS_ENV_KEY, DEFAULT_IRIS_ENV_FILE)
    return [
        CLI_NAME,
        "auth-serve",
        "--auth-store",
        DEFAULT_AUTH_STORE,
        "--auth-dir",
        auth_dir,
        "--origin",
        origin,
        "--allow-loopback-http",
        "--bind",
        DEFAULT_BIND,
        "--port",
        port,
        "--storage",
        DEFAULT_STORAGE,
        "--runtime-dir",
        runtime_dir,
        "--env-file",
        iris_env,
    ]


def build_exec_argv(argv: list[str], env: dict[str, str]) -> list[str]:
    if len(argv) <= 1:
        return build_default_argv(env)
    return [CLI_NAME] + argv[1:]


def run_exec(target: list[str]) -> NoReturn:
    os.execvp(target[0], target)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv) if argv is None else list(argv)
    env = dict(os.environ)
    try:
        target = build_exec_argv(args, env)
    except ValueError as exc:
        sys.stdout.write(
            json.dumps({"error": "http_entrypoint_rejected", "message": str(exc)}) + "\n"
        )
        return 2
    run_exec(target)


if __name__ == "__main__":
    raise SystemExit(main())
