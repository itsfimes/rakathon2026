from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_LAUNCHER_PATH = Path(__file__).parent.parent / "scripts" / "run_converter.py"
_spec = importlib.util.spec_from_file_location("run_converter", _LAUNCHER_PATH)
assert _spec is not None and _spec.loader is not None
_mod: ModuleType = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
launcher: Any = _mod


def test_launcher_requires_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    args = launcher.build_parser().parse_args(
        ["--input", "a.pdf", "--output", str(tmp_path / "out")]
    )
    assert launcher.run_container(args) == 2


def test_launcher_rejects_symlink_input(tmp_path: Path) -> None:
    real = tmp_path / "real.pdf"
    real.write_bytes(b"%PDF-1.4 fake")
    link = tmp_path / "link.pdf"
    link.symlink_to(real)
    args = launcher.build_parser().parse_args(
        ["--input", str(link), "--output", str(tmp_path / "out")]
    )
    assert launcher.run_container(args) == 2


def test_launcher_rejects_nonempty_output(tmp_path: Path) -> None:
    target = tmp_path / "in.pdf"
    target.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "out"
    out.mkdir()
    (out / "old.json").write_text("{}", encoding="utf-8")
    args = launcher.build_parser().parse_args(["--input", str(target), "--output", str(out)])
    assert launcher.run_container(args) == 2


def test_launcher_rejects_loose_secret(tmp_path: Path) -> None:
    target = tmp_path / "in.pdf"
    target.write_bytes(b"%PDF-1.4 fake")
    key = tmp_path / "key"
    key.write_text("k", encoding="utf-8")
    key.chmod(0o644)
    args = launcher.build_parser().parse_args(
        ["--input", str(target), "--output", str(tmp_path / "out"), "--secret-file", str(key)]
    )
    assert launcher.run_container(args) == 2


def test_dockerfile_pins_version_and_nonroot() -> None:
    text = (Path(__file__).parent.parent / "docker" / "converter" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "python:3.13" in text
    assert "OPENCODE_VERSION=2.0.31" in text
    assert "opencode --version" in text
    assert "poppler-utils" in text
    assert "USER 65532" in text
    assert "pip install" in text
    assert "pip check" in text


def test_docker_flags_present_in_launcher_source() -> None:
    text = (Path(launcher.__file__)).read_text(encoding="utf-8")
    for flag in (
        "--read-only",
        "--cap-drop",
        "ALL",
        "no-new-privileges",
        "--pids-limit",
        "--memory",
        "--cpus",
        "--network",
        "--user",
        "/run/secrets/azure_api_key",
        "/work/input/",
        "docker",
    ):
        assert flag in text


def test_launcher_recipe_cache_mount_is_read_only() -> None:
    text = (Path(launcher.__file__)).read_text(encoding="utf-8")
    assert "RAKATHON_RECIPE_CACHE_FILE" in text
    assert "RAKATHON_RECIPE_CACHE_READ_ONLY=1" in text
    assert "/work/recipes/recipes.json:ro" in text
    assert "/work/recipes/recipes.json:rw" not in text
