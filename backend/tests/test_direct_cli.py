from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from direct_fixtures import outcome, provider_response
from test_direct_ingestion import RecordingStore

from rakathon_backend.b5.direct import DirectAdapter
from rakathon_backend.b5.direct_http import DirectHttpTransport, DirectProviderConfig
from rakathon_backend.cli import build_parser
from rakathon_backend.runtime import ingest
from rakathon_backend.runtime.application import BackendApp


@pytest.mark.parametrize("failure,expected", [(False, 0), (True, 1)])
async def test_direct_cli_no_harness_and_failure_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: bool,
    expected: int,
) -> None:
    source = tmp_path / "synthetic.txt"
    source.write_text("Synthetic source")
    config = DirectProviderConfig(
        base_url="https://synthetic.invalid/v1",
        model="synthetic",
        auth_scheme="api-key",
        api_key="synthetic",
        allow_remote=True,
    )
    monkeypatch.setattr(ingest, "direct_config_from_env", lambda: config)
    transport = DirectHttpTransport(
        config,
        transport=httpx.MockTransport(lambda request: provider_response(outcome("incomplete"))),
    )
    monkeypatch.setattr(ingest, "DirectHttpTransport", lambda supplied: transport)
    store = RecordingStore()
    store.fail = failure

    def build(runtime: Path, tokens: dict[str, str], **kwargs: object) -> BackendApp:
        adapter = kwargs.get("ai_adapter")
        assert isinstance(adapter, DirectAdapter)
        return BackendApp(runtime, tokens, store=store, ai_adapter=adapter, ai_mode="direct")

    monkeypatch.setattr(ingest, "BackendApp", build)
    args = build_parser().parse_args(
        [
            "ingest-file",
            "--path",
            str(source),
            "--user",
            "admin",
            "--ai",
            "direct",
            "--patient-id",
            "synthetic-1",
            "--runtime-dir",
            str(tmp_path),
        ]
    )
    assert await ingest.cmd_ingest_file(args) == expected
    printed = json.loads(capsys.readouterr().out)
    if failure:
        assert "error" in printed and "storedCount" not in printed
    else:
        assert printed["status"] == "incomplete" and printed["storedCount"] == 2
        assert printed["needsReview"] is True and printed["storage"] == "mock"
    assert not list(tmp_path.glob("ingest-*"))
