from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

import rakathon_backend.converter.cli as cli_mod
from rakathon_backend.converter.cli import main

FIXTURES = Path(__file__).with_name("fixtures") / "converter"

MOCK_NOTE = "OFFLINE UNIT TEST ONLY: mock model text, never demo output."


def _input(tmp_path: Path) -> Path:
    target = tmp_path / "doc.txt"
    target.write_text("PAT ZEBRA SYN-000001 GLUCOSE 102 mg/dL", encoding="utf-8")
    return target


def _secret(tmp_path: Path) -> Path:
    target = tmp_path / "key"
    target.write_text("RAKATHON_AI_API_KEY=mock-key", encoding="utf-8")
    target.chmod(0o600)
    return target


def _mock_complete() -> str:
    assert MOCK_NOTE
    return json.dumps(
        {
            "status": "complete",
            "bundle": {
                "resourceType": "Bundle",
                "type": "transaction",
                "entry": [
                    {
                        "resource": {"resourceType": "Patient", "id": "p1"},
                        "request": {"method": "PUT", "url": "Patient/p1"},
                    },
                    {
                        "resource": {
                            "resourceType": "DocumentReference",
                            "id": "d1",
                            "status": "current",
                            "content": [{"attachment": {"data": "aGVsbG8="}}],
                        },
                        "request": {"method": "PUT", "url": "DocumentReference/d1"},
                    },
                ],
            },
            "issues": [],
            "evidence": [
                {
                    "resourceType": "Patient",
                    "id": "p1",
                    "sourcePage": 1,
                    "literalQuote": "PAT ZEBRA SYN-000001",
                    "field": "/id",
                },
                {
                    "resourceType": "DocumentReference",
                    "id": "d1",
                    "sourcePage": 1,
                    "literalQuote": "GLUCOSE 102 mg/dL",
                    "field": "/content/0/attachment/data",
                },
            ],
        }
    )


def test_mock_model_complete_writes_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert MOCK_NOTE

    def _fake(*args: Any, **kwargs: Any) -> str:
        return _mock_complete()

    monkeypatch.setattr(cli_mod, "run_model_once", _fake)
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(_input(tmp_path)),
            "--output",
            str(out),
            "--allow-azure",
            "--secret-file",
            str(_secret(tmp_path)),
        ]
    )
    assert code == 0
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "complete"
    assert result["model"]["present"] is True
    assert result["needsReview"] is True
    assert result["writeEligible"] is False
    bundle = json.loads((out / "bundle.json").read_text(encoding="utf-8"))
    assert bundle["meta"]["source"].startswith("urn:sha256:")
    assert bundle["resourceType"] == "Bundle"


def test_mock_model_provenance_key_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert MOCK_NOTE
    doc = json.loads(_mock_complete())
    doc["provenance"] = {"by": "model"}

    def _fake(*args: Any, **kwargs: Any) -> str:
        return json.dumps(doc)

    monkeypatch.setattr(cli_mod, "run_model_once", _fake)
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(_input(tmp_path)),
            "--output",
            str(out),
            "--allow-azure",
            "--secret-file",
            str(_secret(tmp_path)),
        ]
    )
    assert code == 3
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "manual-review"
    assert not (out / "bundle.json").exists()


def test_mock_model_garbage_yields_safe_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert MOCK_NOTE

    def _fake(*args: Any, **kwargs: Any) -> str:
        return "not json at all, just prose"

    monkeypatch.setattr(cli_mod, "run_model_once", _fake)
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(_input(tmp_path)),
            "--output",
            str(out),
            "--allow-azure",
            "--secret-file",
            str(_secret(tmp_path)),
        ]
    )
    assert code == 3
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "manual-review"
    assert result["bundle"] is None
    assert not (out / "bundle.json").exists()


def test_check_mode_needs_no_network(tmp_path: Path) -> None:
    code = main(
        [
            "--input",
            str(FIXTURES / "fixture_01_lab_report.pdf"),
            "--output",
            str(tmp_path / "out"),
            "--check",
        ]
    )
    assert code == 0


def test_extract_mode_writes_text_and_provenance(tmp_path: Path) -> None:
    out = tmp_path / "out"
    code = main(
        [
            "--input",
            str(FIXTURES / "fixture_02_discharge_narrative.pdf"),
            "--output",
            str(out),
            "--extract",
        ]
    )
    assert code == 0
    text = (out / "extract.txt").read_text(encoding="utf-8")
    assert "[page 1]" in text and "[page 2]" in text
    assert "SYN-000002" in text
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["pages"] == 2
    assert stat.S_IMODE(os.stat(out / "extract.txt").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(out / "provenance.json").st_mode) == 0o600
