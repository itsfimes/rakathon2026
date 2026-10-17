from __future__ import annotations

import subprocess
import sys

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
assert "rakathon_backend.runtime.ai_factory" not in sys.modules
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
assert "rakathon_backend.runtime.ai_factory" not in sys.modules
for name, module in tuple(sys.modules.items()):
    if name.startswith("rakathon_backend."):
        source = getattr(module, "__file__", None)
        assert source is None or Path(source).is_file(), name
print("isolated-path-pass")
"""


def test_fresh_cli_import_and_direct_ingestion() -> None:
    result = subprocess.run(
        [sys.executable, "-W", "error", "-c", SCRIPT],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "isolated-path-pass"
