from __future__ import annotations

import subprocess
import sys

import pytest

SCRIPT = r"""
import asyncio
import contextlib
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

def forbidden(*args, **kwargs):
    raise AssertionError("A direct/inspection path attempted subprocess execution")

subprocess.Popen = forbidden
asyncio.create_subprocess_exec = forbidden
asyncio.create_subprocess_shell = forbidden
cli = importlib.import_module("rakathon_backend.cli")
ingest = importlib.import_module("rakathon_backend.runtime.ingest")
assert not any(name.startswith("rakathon_backend.b5.opencode") for name in sys.modules)
assert "rakathon_backend.runtime.legacy_ai" not in sys.modules
if sys.argv[1] == "legacy":
    for name in list(os.environ):
        if name.startswith("RAKATHON_AI_") or name == "AI_DISABLED":
            del os.environ[name]
    factory = importlib.import_module("rakathon_backend.runtime.ai_factory")
    config = factory.ai_config_from_env()
    assert not config.ready
    assert "rakathon_backend.b5.opencode.adapter" in sys.modules
else:
    httpx = importlib.import_module("httpx")
    direct_http = importlib.import_module("rakathon_backend.b5.direct_http")
    config = direct_http.DirectProviderConfig(
        base_url="https://synthetic.invalid/v1", model="synthetic",
        auth_scheme="api-key", api_key="synthetic-key", allow_remote=True,
    )
    original_transport = direct_http.DirectHttpTransport
    calls = []
    def send(request):
        calls.append(request)
        outcome = {"status":"manual-review", "bundle":None, "issues":[{
            "code":"missing-context", "resourceType":None, "detail":"Synthetic context missing"
        }]}
        return httpx.Response(200, json={"choices":[{
            "finish_reason":"stop", "message":{"content":json.dumps(outcome)}
        }]})
    ingest.direct_config_from_env = lambda: config
    ingest.DirectHttpTransport = lambda supplied: original_transport(
        supplied, transport=httpx.MockTransport(send)
    )
    os.environ["AI_DISABLED"] = "0"
    os.environ.pop("RAKATHON_AI_KILL_FILE", None)
    with tempfile.TemporaryDirectory(prefix="isolate-", dir="/tmp/opencode") as runtime:
        source = Path(runtime) / "synthetic.txt"
        source.write_text("Synthetic source")
        args = cli.build_parser().parse_args([
            "ingest-file", "--ai", "direct", "--path", str(source),
            "--user", "admin", "--runtime-dir", runtime
        ])
        with contextlib.redirect_stdout(io.StringIO()):
            assert asyncio.run(ingest.cmd_ingest_file(args)) == 0
    assert len(calls) == 1
    assert not any(name.startswith("rakathon_backend.b5.opencode") for name in sys.modules)
    assert "rakathon_backend.runtime.legacy_ai" not in sys.modules
print("isolated-path-pass")
"""


@pytest.mark.parametrize("mode", ["direct", "legacy"])
def test_fresh_cli_import_and_mode_selected_factory(mode: str) -> None:
    result = subprocess.run(
        [sys.executable, "-W", "error", "-c", SCRIPT, mode],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "isolated-path-pass"
