from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

import pytest
from docx_samples import MARKER, make_docx

from rakathon_backend.runtime.ingest import cmd_ingest_file


def _args(path: str, user: str = "admin", **extra: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "path": path,
        "user": user,
        "ai": "mock",
        "runtime_dir": None,
        "output_file": None,
    }
    values.update(extra)
    return argparse.Namespace(**values)


def _docx_file(tmp_path: Path, name: str = "note.docx") -> str:
    target = tmp_path / name
    target.write_bytes(make_docx([("p", f"visit summary {MARKER}"), ("t", [["k", "v"]])]))
    return str(target)


async def test_cli_mock_summary_has_no_clinical_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _docx_file(tmp_path)
    rc = await cmd_ingest_file(_args(path))
    assert rc == 0
    out = capsys.readouterr().out
    summary = json.loads(out)
    assert summary["mode"] == "mock"
    assert summary["manualReview"] is True
    assert summary["storedCount"] == 0
    assert len(summary["sha256"]) == 64
    assert MARKER not in out
    assert "visit summary" not in out


async def test_cli_is_deterministic(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _docx_file(tmp_path)
    await cmd_ingest_file(_args(path))
    first = json.loads(capsys.readouterr().out)["sha256"]
    await cmd_ingest_file(_args(path))
    second = json.loads(capsys.readouterr().out)["sha256"]
    assert first == second


async def test_cli_denied_user_reports_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _docx_file(tmp_path)
    rc = await cmd_ingest_file(_args(path, user="viewer"))
    assert rc == 1
    out = capsys.readouterr().out
    assert MARKER not in out
    assert "AuthError" in out


async def test_cli_unknown_user_reports_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _docx_file(tmp_path)
    rc = await cmd_ingest_file(_args(path, user="ghost"))
    assert rc == 1
    assert MARKER not in capsys.readouterr().out


async def test_cli_rejects_suffix_and_symlink(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "note.exe"
    bad.write_bytes(b"x")
    assert await cmd_ingest_file(_args(str(bad))) == 2
    capsys.readouterr()
    link = tmp_path / "link.docx"
    link.symlink_to(_docx_file(tmp_path, name="real.docx"))
    assert await cmd_ingest_file(_args(str(link))) == 2
    assert MARKER not in capsys.readouterr().out


async def test_cli_output_file_is_owner_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _docx_file(tmp_path)
    target = tmp_path / "summary.json"
    rc = await cmd_ingest_file(_args(path, output_file=str(target)))
    assert rc == 0
    capsys.readouterr()
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    body = json.loads(target.read_text(encoding="utf-8"))
    assert body["mode"] == "mock"
    assert MARKER not in target.read_text(encoding="utf-8")


async def test_cli_owned_runtime_never_clobbers_live_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("live", encoding="utf-8")
    path = _docx_file(tmp_path)
    rc = await cmd_ingest_file(_args(path, runtime_dir=str(tmp_path)))
    assert rc == 0
    capsys.readouterr()
    assert sentinel.read_text(encoding="utf-8") == "live"
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith("ingest-")]
    assert leftovers == []
