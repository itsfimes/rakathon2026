from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any

import httpx
import pytest
from direct_fixtures import outcome, response

from rakathon_backend.b1.outcome import prepare_import
from rakathon_backend.b2.ingestion import persist_import
from rakathon_backend.b2.memory import MemoryStorage
from rakathon_backend.b2.service import B2Service
from rakathon_backend.b5.direct import DirectAdapter
from rakathon_backend.b5.direct_http import DirectHttpTransport, DirectProviderConfig
from rakathon_backend.cli import build_parser
from rakathon_backend.common.contracts import DataKind
from rakathon_backend.common.errors import ContractError, TransportError
from rakathon_backend.common.rpc import new_envelope
from rakathon_backend.runtime import commands, ingest
from rakathon_backend.runtime.application import BackendApp, fresh_tokens


def enabled_env(monkeypatch: pytest.MonkeyPatch, kill_file: Path) -> None:
    for key, value in {
        "RAKATHON_AI_ENABLE": "1",
        "AI_DISABLED": "0",
        "RAKATHON_AI_PROVIDER_KIND": "azure",
        "RAKATHON_AI_BASE_URL": "https://synthetic.invalid/v1",
        "RAKATHON_AI_MODEL": "synthetic",
        "RAKATHON_AI_API_KEY": "synthetic-key",
        "RAKATHON_AI_ALLOW_REMOTE": "1",
        "RAKATHON_AI_KILL_FILE": str(kill_file),
    }.items():
        monkeypatch.setenv(key, value)


async def test_preexisting_kill_refuses_cli_and_serve_without_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    kill_file = tmp_path / "private-kill-marker"
    kill_file.write_text("synthetic stop")
    enabled_env(monkeypatch, kill_file)
    calls: list[object] = []

    def forbidden_transport(config: object) -> DirectHttpTransport:
        calls.append(config)
        raise AssertionError("Transport must not be constructed after a kill")

    monkeypatch.setattr(ingest, "DirectHttpTransport", forbidden_transport)
    monkeypatch.setattr(commands, "DirectHttpTransport", forbidden_transport)
    source = tmp_path / "synthetic.txt"
    source.write_text("Synthetic source")
    args = build_parser().parse_args(
        [
            "ingest-file",
            "--path",
            str(source),
            "--user",
            "admin",
            "--ai",
            "direct",
            "--runtime-dir",
            str(tmp_path),
        ]
    )
    assert await ingest.cmd_ingest_file(args) == 2
    assert await commands.cmd_serve(tmp_path / "serve", "mock", "direct", 1.0) == 2
    assert calls == [] and not list(tmp_path.glob("ingest-*"))
    assert str(kill_file) not in capsys.readouterr().out


async def test_cli_passes_kill_file_and_refuses_config_start_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kill_file = tmp_path / "kill"
    enabled_env(monkeypatch, kill_file)
    config = DirectProviderConfig(
        base_url="https://synthetic.invalid/v1",
        model="synthetic",
        auth_scheme="api-key",
        api_key="synthetic-key",
        allow_remote=True,
    )
    calls: list[httpx.Request] = []

    def raced_config() -> DirectProviderConfig:
        kill_file.write_text("synthetic stop after configuration")
        return config

    def send(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("Killed CLI must not dispatch")

    transport = DirectHttpTransport(config, transport=httpx.MockTransport(send))
    monkeypatch.setattr(ingest, "direct_config_from_env", raced_config)
    monkeypatch.setattr(ingest, "DirectHttpTransport", lambda supplied: transport)
    source = tmp_path / "synthetic.txt"
    source.write_text("Synthetic source")
    args = build_parser().parse_args(
        [
            "ingest-file",
            "--path",
            str(source),
            "--user",
            "admin",
            "--ai",
            "direct",
            "--runtime-dir",
            str(tmp_path),
        ]
    )
    try:
        assert await ingest.cmd_ingest_file(args) == 1
        assert calls == [] and not list(tmp_path.glob("ingest-*"))
    finally:
        await transport.aclose()


async def test_cli_live_import_is_disabled_before_input_or_provider() -> None:
    args = build_parser().parse_args(
        [
            "ingest-file",
            "--path",
            "/unread-synthetic-input",
            "--user",
            "admin",
            "--ai",
            "direct",
            "--storage",
            "iris-fhir",
        ]
    )
    assert await ingest.cmd_ingest_file(args) == 2


@pytest.mark.parametrize("in_flight", [False, True])
async def test_file_kill_blocks_dispatch_gap_and_cancels_active_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, in_flight: bool
) -> None:
    kill_file = tmp_path / "kill"
    monkeypatch.setenv("AI_DISABLED", "0")
    release, started, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls: list[httpx.Request] = []
    original_watch = BackendApp._kill_watch

    async def gated_watch(self: BackendApp) -> None:
        await release.wait()
        await original_watch(self)

    async def send(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return response("unreachable")

    monkeypatch.setattr(BackendApp, "_kill_watch", gated_watch)
    config = DirectProviderConfig(
        base_url="https://synthetic.invalid/v1",
        model="synthetic",
        auth_scheme="bearer",
        api_key="synthetic-key",
        allow_remote=True,
    )
    adapter = DirectAdapter(DirectHttpTransport(config, transport=httpx.MockTransport(send)))
    app = BackendApp(
        tmp_path / "uds",
        fresh_tokens(),
        ai_adapter=adapter,
        ai_mode="direct",
        kill_file=kill_file,
    )
    await app.start()
    try:
        if not in_flight:
            kill_file.write_text("synthetic stop")
        call = asyncio.create_task(
            app.frontend_client("admin").call(
                new_envelope(
                    source="frontend:admin",
                    target="b4",
                    action="ai.complete",
                    data_kind=DataKind.PROPRIETARY,
                    payload={"prompt": "Synthetic"},
                    user_id="admin",
                ),
                expect_source="b4",
            )
        )
        if in_flight:
            await asyncio.wait_for(started.wait(), 2)
            kill_file.write_text("synthetic stop")
            release.set()
            await asyncio.wait_for(cancelled.wait(), 2)
        with pytest.raises(TransportError):
            await asyncio.wait_for(call, 2)
        assert len(calls) == (1 if in_flight else 0)
    finally:
        release.set()
        await app.close()


class MutationStore(MemoryStorage):
    def __init__(self) -> None:
        super().__init__()
        self.transactions = 0
        self.writes = 0

    def fhir_transaction(self, bundle: dict[str, Any]) -> dict[str, Any]:
        self.transactions += 1
        return super().fhir_transaction(bundle)

    def fhir_write(self, resource: dict[str, Any]) -> dict[str, Any]:
        self.writes += 1
        return super().fhir_write(resource)


async def allow(*, user_id: str, action: str, correlation_id: str) -> bool:
    return True


@pytest.mark.parametrize(
    "variant",
    [
        "missing-context",
        "wrapped-missing-context",
        "missing-condition",
        "conflicting-tag",
        "conflicting-context",
        "plain-tagged",
        "plain-source-only",
        "plain-tag-only",
        "plain-with-context",
        "transaction-source-only",
        "live-import",
    ],
)
async def test_reserved_import_cannot_bypass_b2(variant: str) -> None:
    prepared = prepare_import(outcome("incomplete"), "urn:sha256:" + "a" * 64, "synthetic-1")
    bundle = prepared["bundle"]
    context = {key: prepared[key] for key in ("status", "issues", "sourceUrn", "patientId")}
    payload = {"bundle": bundle, "ingestion": context}
    if variant == "missing-context":
        payload = bundle
    elif variant == "wrapped-missing-context":
        payload = {"bundle": bundle}
    elif variant == "missing-condition":
        del bundle["entry"][0]["request"]["ifNoneMatch"]
    elif variant == "conflicting-tag":
        bundle["entry"][0]["resource"]["meta"]["tag"][0]["code"] = "complete"
    elif variant == "conflicting-context":
        context["status"] = "complete"
    elif variant.startswith("plain-"):
        payload = bundle["entry"][0]["resource"]
        if variant == "plain-source-only":
            del payload["meta"]["tag"]
        elif variant == "plain-tag-only":
            del payload["meta"]["source"]
        elif variant == "plain-with-context":
            payload["ingestion"] = context
    elif variant == "transaction-source-only":
        payload = bundle
        for entry in bundle["entry"]:
            del entry["resource"]["meta"]["tag"]
    store = MutationStore()
    if variant not in (
        "missing-condition",
        "conflicting-tag",
        "conflicting-context",
        "live-import",
    ):
        store.fhir[("Patient", "synthetic-1")] = {
            "resourceType": "Patient",
            "id": "synthetic-1",
            "active": True,
        }
    before = copy.deepcopy(store.fhir)
    mode = "iris-fhir" if variant == "live-import" else "mock"
    service = B2Service(store, allow, mode=mode)
    request = new_envelope(
        source="b4",
        target="b2",
        action="fhir.write",
        data_kind=DataKind.FHIR,
        payload=payload,
        user_id="admin",
    )
    with pytest.raises(ContractError):
        await service.handle(request)
    assert store.transactions == store.writes == 0 and store.fhir == before


async def test_untagged_standalone_write_is_preserved() -> None:
    store = MutationStore()
    resource = {"resourceType": "Patient", "id": "synthetic", "active": False}
    reply = await B2Service(store, allow).handle(
        new_envelope(
            source="b4",
            target="b2",
            action="fhir.write",
            data_kind=DataKind.FHIR,
            payload=resource,
            user_id="admin",
        )
    )
    assert reply.payload["count"] == 1 and store.writes == 1 and store.transactions == 0
    assert store.fhir[("Patient", "synthetic")] == resource


def test_import_persists_validated_snapshot_not_mutated_caller_payload() -> None:
    prepared = prepare_import(outcome("incomplete"), "urn:sha256:" + "a" * 64, "synthetic-1")
    bundle = prepared["bundle"]
    context = {key: prepared[key] for key in ("status", "issues", "sourceUrn", "patientId")}
    before_context = copy.deepcopy(context)

    class MutatingReader(MutationStore):
        def fhir_read(self, resource_type: str, rid: str) -> dict[str, Any] | None:
            bundle["entry"][0]["resource"]["active"] = True
            return None

    store = MutatingReader()
    persist_import(store, bundle, context)
    assert store.transactions == 1 and store.writes == 0
    assert store.fhir[("Patient", "synthetic-1")]["active"] is False
    assert context == before_context
