from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
DOCKER_DIR = BACKEND_DIR / "docker" / "http"


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


entrypoint = load_module("http_entrypoint_under_test", DOCKER_DIR / "entrypoint.py")
healthcheck = load_module("http_healthcheck_under_test", DOCKER_DIR / "healthcheck.py")


def test_default_argv_is_persistent_demo_iris_fhir_loopback() -> None:
    argv = entrypoint.build_exec_argv([], {})
    assert argv[0] == "rakathon-backend"
    assert argv[1] == "auth-serve"
    assert argv[argv.index("--auth-store") + 1] == "demo"
    assert argv[argv.index("--auth-dir") + 1] == "/state/auth"
    assert argv[argv.index("--origin") + 1] == "http://localhost:5173"
    assert "--allow-loopback-http" in argv
    assert argv[argv.index("--bind") + 1] == "127.0.0.1"
    assert argv[argv.index("--port") + 1] == "18765"
    assert argv[argv.index("--storage") + 1] == "iris-fhir"
    assert argv[argv.index("--runtime-dir") + 1] == "/run/rakathon"
    assert argv[argv.index("--env-file") + 1] == "/run/secrets/iris.env"
    assert "--assistant" not in argv
    assert "--assistant-enable" not in argv
    assert "--converter-enable" not in argv
    assert "--converter-store" not in argv
    assert "--converter-secret-file" not in argv
    assert "mock" not in argv


def test_default_env_overrides_apply() -> None:
    env = {
        "RAKATHON_HTTP_PORT": "18766",
        "RAKATHON_HTTP_ORIGIN": "http://localhost:5174",
        "RAKATHON_HTTP_AUTH_DIR": "/state/other",
        "RAKATHON_HTTP_RUNTIME_DIR": "/run/other",
        "RAKATHON_HTTP_IRIS_ENV_FILE": "/run/secrets/other.env",
    }
    argv = entrypoint.build_exec_argv([], env)
    assert argv[argv.index("--port") + 1] == "18766"
    assert argv[argv.index("--origin") + 1] == "http://localhost:5174"
    assert argv[argv.index("--auth-dir") + 1] == "/state/other"
    assert argv[argv.index("--runtime-dir") + 1] == "/run/other"
    assert argv[argv.index("--env-file") + 1] == "/run/secrets/other.env"


def test_default_env_rejects_empty_port_and_bad_port() -> None:
    with pytest.raises(ValueError):
        entrypoint.build_exec_argv([], {"RAKATHON_HTTP_PORT": ""})
    with pytest.raises(ValueError):
        entrypoint.build_exec_argv([], {"RAKATHON_HTTP_PORT": "   "})
    with pytest.raises(ValueError):
        entrypoint.build_exec_argv([], {"RAKATHON_HTTP_PORT": "not-a-port"})
    with pytest.raises(ValueError):
        entrypoint.build_exec_argv([], {"RAKATHON_HTTP_PORT": "0"})
    with pytest.raises(ValueError):
        entrypoint.build_exec_argv([], {"RAKATHON_HTTP_PORT": "70000"})
    with pytest.raises(ValueError):
        entrypoint.build_exec_argv([], {"RAKATHON_HTTP_ORIGIN": "  "})


def test_explicit_auth_commands_pass_through() -> None:
    for cmd in ("auth-init", "auth-user-add", "auth-serve"):
        out = entrypoint.build_exec_argv(
            ["entrypoint", cmd, "--auth-store", "demo", "--auth-dir", "/state/auth"], {}
        )
        assert out == [
            "rakathon-backend",
            cmd,
            "--auth-store",
            "demo",
            "--auth-dir",
            "/state/auth",
        ]


def test_healthcheck_port_and_proxy_path_env() -> None:
    assert healthcheck.port_from_env({}) == 18765
    assert healthcheck.port_from_env({"RAKATHON_HTTP_PORT": "18765"}) == 18765
    assert healthcheck.proxy_path_from_env({}) == Path("/state/auth/proxy.key")
    with pytest.raises(ValueError):
        healthcheck.port_from_env({"RAKATHON_HTTP_PORT": ""})
    with pytest.raises(ValueError):
        healthcheck.port_from_env({"RAKATHON_HTTP_PORT": "nope"})
    with pytest.raises(ValueError):
        healthcheck.port_from_env({"RAKATHON_HTTP_PORT": "99999"})
    with pytest.raises(ValueError):
        healthcheck.proxy_path_from_env({"RAKATHON_HTTP_PROXY_KEY_FILE": "  "})


def test_healthcheck_uses_proxy_header_and_liveness_only() -> None:
    text = (DOCKER_DIR / "healthcheck.py").read_text(encoding="utf-8")
    assert "x-rakathon-proxy-key" in text
    assert "/health" in text
    assert "liveness" in text
    assert '"status"' in text or "'status'" in text or '.get("status")' in text
    assert "RAKATHON_IRIS_FHIR_PASSWORD" not in text
    assert "RAKATHON_IRIS_FHIR_USER" not in text
    assert "getpass" not in text
    assert "Cookie" not in text
    assert "/api/v1/auth/session" not in text


def test_dockerignore_whitelists_only_safe_paths() -> None:
    lines = (DOCKER_DIR / "Dockerfile.dockerignore").read_text(encoding="utf-8").splitlines()
    assert lines[0].strip() == "*"
    text = "\n".join(lines)
    assert "!pyproject.toml" in lines
    assert "!README.md" in lines
    assert "!src/" in lines
    assert "!scripts/run_converter.py" in lines
    assert "!docker/http/entrypoint.py" in lines
    assert "!docker/http/healthcheck.py" in lines
    assert "!docker/http/Dockerfile" in lines
    assert "!.env" not in text
    assert "!iris.env" not in text
    assert "!runtime" not in text
    assert "!tests" not in text
    assert "!.venv" not in text
    assert "!backend" not in text


def test_dockerfile_http_default_has_no_docker_cli() -> None:
    text = (DOCKER_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert "AS http-base" in text
    assert "http-with-converter" in text
    assert "COPY --from=docker:27.5.1-cli" in text
    assert text.count("COPY --from") == 1
    assert "USER 65532" in text
    assert "USER 0" not in text
    assert "HEALTHCHECK" in text
    assert "healthcheck.py" in text
    assert "entrypoint.py" in text
    assert "pip check" in text
    assert "prompt" in text
    assert "COPY src" in text
    assert "COPY pyproject.toml" in text
    assert "COPY . " not in text
    assert "COPY ." not in text
    assert "--converter-enable" not in text
    assert "--assistant" not in text
    lines = text.splitlines()
    names = [line.split("AS", 1)[1].strip() for line in lines if line.startswith("FROM")]
    assert names[0] == "http-base"
    assert "http" in names
    assert "http-with-converter" in names
    assert names[-1] == "http"
    start = max(i for i, line in enumerate(lines) if line.strip() == "FROM http-base AS http")
    tail = "\n".join(lines[start:])
    assert "docker:" not in tail
    assert "COPY --from" not in tail


def test_entrypoint_source_never_enables_ai_or_mock() -> None:
    text = (DOCKER_DIR / "entrypoint.py").read_text(encoding="utf-8")
    assert "--assistant" not in text
    assert "--converter-enable" not in text
    assert '"mock"' not in text
    assert "'mock'" not in text
