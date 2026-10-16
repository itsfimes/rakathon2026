from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from rakathon_backend.common.errors import ContractError
from rakathon_backend.web.config import SIZE_CAP, generate_proxy_key, load_proxy_key


def write_key(target: Path, body: str) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(str(target), flags, 0o600)
    try:
        os.write(fd, body.encode("ascii"))
    finally:
        os.close(fd)
    os.chmod(str(target), 0o600)


def test_roundtrip_private_dir(tmp_path: Path) -> None:
    os.chmod(str(tmp_path), 0o700)
    target = tmp_path / "proxy.key"
    token = generate_proxy_key(target)
    assert load_proxy_key(target) == token


def test_unsafe_parent_rejected(tmp_path: Path) -> None:
    os.chmod(str(tmp_path), 0o700)
    target = tmp_path / "proxy.key"
    token = generate_proxy_key(target)
    assert load_proxy_key(target) == token
    os.chmod(str(tmp_path), 0o755)
    try:
        with pytest.raises(ContractError):
            load_proxy_key(target)
    finally:
        os.chmod(str(tmp_path), 0o700)
    assert load_proxy_key(target) == token


def test_symlink_parent_and_file_rejected(tmp_path: Path) -> None:
    os.chmod(str(tmp_path), 0o700)
    target = tmp_path / "proxy.key"
    generate_proxy_key(target)
    link = tmp_path / "link.key"
    link.symlink_to(target)
    with pytest.raises(ContractError):
        load_proxy_key(link)
    outer = tmp_path / "outer"
    outer.mkdir(mode=0o700)
    alias = outer / "alias"
    alias.symlink_to(tmp_path)
    with pytest.raises(ContractError):
        load_proxy_key(alias / "proxy.key")


def test_mode_and_size_rejected(tmp_path: Path) -> None:
    os.chmod(str(tmp_path), 0o700)
    target = tmp_path / "proxy.key"
    generate_proxy_key(target)
    os.chmod(str(target), 0o644)
    with pytest.raises(ContractError):
        load_proxy_key(target)
    assert stat.S_IMODE(os.stat(target).st_mode) != 0o600
    os.chmod(str(target), 0o600)
    big = tmp_path / "big.key"
    write_key(big, "K" * (SIZE_CAP + 1))
    with pytest.raises(ContractError):
        load_proxy_key(big)
    empty = tmp_path / "empty.key"
    write_key(empty, "")
    with pytest.raises(ContractError):
        load_proxy_key(empty)
