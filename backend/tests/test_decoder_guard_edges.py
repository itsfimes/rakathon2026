from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.converter.adaptive import AdaptiveManual, adapt_bytes
from rakathon_backend.converter.archive_security import member_name_dangerous
from rakathon_backend.converter.cli import _commit_recipe_if_validated
from rakathon_backend.converter.detect import detect
from rakathon_backend.converter.planner import RecipeCache

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _valid_recipe() -> dict[str, Any]:
    return {"version": 1, "steps": [{"op": "charset", "charset": "utf-8", "maxChars": 2000}]}


def _info(pending: Any) -> dict[str, Any]:
    return {"pendingRecipe": pending, "fingerprint": "fp-guard-edge-001"}


def _ole_raw(marker: bytes) -> bytes:
    return OLE_MAGIC + bytes(512) + marker + bytes(2048)


def test_hidden_executable_members_rejected() -> None:
    assert member_name_dangerous(".evil.exe") is True
    assert member_name_dangerous(".hidden.bat") is True
    assert member_name_dangerous("payload/.evil.exe") is True
    assert member_name_dangerous("payload\\.hidden.ps1") is True


def test_benign_hidden_members_allowed() -> None:
    assert member_name_dangerous(".profile") is False
    assert member_name_dangerous(".DS_Store") is False
    assert member_name_dangerous("docs/.keep") is False


def test_macro_members_still_rejected() -> None:
    assert member_name_dangerous("word/vbaProject.bin") is True
    assert member_name_dangerous("xl/macros/sheet.xml") is True
    assert member_name_dangerous("word/activeX/ax1.bin") is True


def test_valid_pending_recipe_promotes_to_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "recipes.json"
    monkeypatch.setenv("RAKATHON_RECIPE_CACHE_FILE", str(cache))
    monkeypatch.delenv("RAKATHON_RECIPE_CACHE_READ_ONLY", raising=False)
    _commit_recipe_if_validated(_info(_valid_recipe()), "complete")
    assert cache.exists()
    loaded = RecipeCache(cache).get("fp-guard-edge-001")
    assert loaded == _valid_recipe()


def test_malformed_pending_recipe_never_learned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "recipes.json"
    monkeypatch.setenv("RAKATHON_RECIPE_CACHE_FILE", str(cache))
    monkeypatch.delenv("RAKATHON_RECIPE_CACHE_READ_ONLY", raising=False)
    _commit_recipe_if_validated(
        _info({"version": 1, "steps": [{"op": "shell", "cmd": "id"}]}), "complete"
    )
    assert not cache.exists()


def test_enriched_pending_recipe_with_phi_never_learned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "recipes.json"
    monkeypatch.setenv("RAKATHON_RECIPE_CACHE_FILE", str(cache))
    monkeypatch.delenv("RAKATHON_RECIPE_CACHE_READ_ONLY", raising=False)
    enriched: dict[str, Any] = dict(_valid_recipe())
    enriched["patient"] = "MRN-12345"
    enriched["note"] = "secret clinical quote"
    _commit_recipe_if_validated(_info(enriched), "complete")
    assert not cache.exists()


def test_non_complete_status_never_promotes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "recipes.json"
    monkeypatch.setenv("RAKATHON_RECIPE_CACHE_FILE", str(cache))
    monkeypatch.delenv("RAKATHON_RECIPE_CACHE_READ_ONLY", raising=False)
    _commit_recipe_if_validated(_info(_valid_recipe()), "manual-review")
    assert not cache.exists()


def test_read_only_env_flag_skips_cache_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "recipes.json"
    monkeypatch.setenv("RAKATHON_RECIPE_CACHE_FILE", str(cache))
    monkeypatch.setenv("RAKATHON_RECIPE_CACHE_READ_ONLY", "1")
    _commit_recipe_if_validated(_info(_valid_recipe()), "complete")
    assert not cache.exists()


def test_unwritable_cache_location_skips_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "recipes.json"
    monkeypatch.setenv("RAKATHON_RECIPE_CACHE_FILE", str(cache))
    monkeypatch.delenv("RAKATHON_RECIPE_CACHE_READ_ONLY", raising=False)
    monkeypatch.setattr(os, "access", lambda _path, _mode: False)
    _commit_recipe_if_validated(_info(_valid_recipe()), "complete")
    assert not cache.exists()


def test_shared_cache_file_carries_no_phi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / "recipes.json"
    monkeypatch.setenv("RAKATHON_RECIPE_CACHE_FILE", str(cache))
    monkeypatch.delenv("RAKATHON_RECIPE_CACHE_READ_ONLY", raising=False)
    _commit_recipe_if_validated(_info(_valid_recipe()), "complete")
    body = cache.read_text(encoding="utf-8")
    assert "MRN" not in body
    assert json.loads(body)["fp-guard-edge-001"] == _valid_recipe()


def test_encrypted_package_ole_detected() -> None:
    raw = _ole_raw("EncryptedPackage".encode("utf-16-le"))
    found = detect(raw, ".bin", "workbook.bin")
    assert found.category == "ole"
    assert found.encrypted_hint is True


def test_plain_ole_without_marker_not_flagged_encrypted() -> None:
    raw = _ole_raw(b"WordDocument")
    found = detect(raw, ".bin", "legacy.bin")
    assert found.category == "ole"
    assert found.encrypted_hint is False


def test_encrypted_package_ole_needs_manual_review() -> None:
    raw = _ole_raw("EncryptedPackage".encode("utf-16-le"))
    try:
        adapt_bytes(raw, ".bin", "workbook.bin")
    except AdaptiveManual as exc:
        assert exc.code == "encrypted_no_extract"
    else:
        raise AssertionError("expected manual review for encrypted package")


def test_zip_carrying_encrypted_package_hints_encryption() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as handle:
        handle.writestr("EncryptedPackage", b"x")
        handle.writestr("note.txt", b"hello world readable clinical text sample")
    found = detect(buf.getvalue(), ".bin", "pkg.bin")
    assert found.encrypted_hint is True
    try:
        adapt_bytes(buf.getvalue(), ".bin", "pkg.bin")
    except AdaptiveManual as exc:
        assert exc.code == "encrypted_no_extract"
    else:
        raise AssertionError("expected manual review for encrypted package")
