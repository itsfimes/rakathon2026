from __future__ import annotations

import hashlib
import os
import stat
import struct
import subprocess
from pathlib import Path
from typing import Any

import pytest

import rakathon_backend.converter.file_inputs as file_inputs_mod
from rakathon_backend.converter.file_inputs import (
    FileInputError,
    inspect_image,
    needs_file_lane,
    prepare_file_inputs,
    sniff_image_kind,
)


def _png(*, width: int = 32, height: int = 16) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\x00\x00\x00\x00"


def _jpeg(*, width: int = 32, height: int = 16) -> bytes:
    seg = b"\x08" + struct.pack(">H", height) + struct.pack(">H", width) + b"\x01\x01\x11\x00"
    return b"\xff\xd8" + b"\xff\xc0" + struct.pack(">H", len(seg) + 2) + seg + b"\xff\xd9"


def _gif(*, width: int = 32, height: int = 16, animated: bool = False) -> bytes:
    out = b"GIF89a" + struct.pack("<HH", width, height)
    if animated:
        out += b"!\xff\x0bNETSCAPE2.0"
    return out + b"\x00" * 4


def _webp_vp8(*, width: int = 32, height: int = 16) -> bytes:
    body = b"\x00\x00\x00" + b"\x9d\x01\x2a" + struct.pack("<H", width) + struct.pack("<H", height)
    chunk = b"VP8 " + struct.pack("<I", len(body)) + body
    return b"RIFF" + struct.pack("<I", len(chunk) + 4) + b"WEBP" + chunk


def _webp_vp8x(*, width: int = 32, height: int = 16, animated: bool = True) -> bytes:
    payload = bytes([0x02 if animated else 0x00]) + b"\x00\x00\x00"
    payload += (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    chunk = b"VP8X" + struct.pack("<I", len(payload)) + payload
    return b"RIFF" + struct.pack("<I", len(chunk) + 4) + b"WEBP" + chunk


def _webp_vp8l(*, width: int = 32, height: int = 16) -> bytes:
    bits = ((height - 1) << 14) | (width - 1)
    chunk = b"VP8L" + struct.pack("<I", 5) + b"\x2f" + struct.pack("<I", bits)
    return b"RIFF" + struct.pack("<I", len(chunk) + 4) + b"WEBP" + chunk


def _completed(stdout: bytes, code: int = 0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(args=["poppler"], returncode=code, stdout=stdout)


def test_sniff_image_kinds() -> None:
    assert sniff_image_kind(_png()) == "png"
    assert sniff_image_kind(_jpeg()) == "jpeg"
    assert sniff_image_kind(_gif()) == "gif"
    assert sniff_image_kind(_webp_vp8()) == "webp"
    assert sniff_image_kind(_webp_vp8x()) == "webp"
    assert sniff_image_kind(_webp_vp8l()) == "webp"
    assert sniff_image_kind(b"II*\x00rest") == "tiff"
    assert sniff_image_kind(b"MM\x00*rest") == "tiff"
    assert sniff_image_kind(b"plain text words") is None
    assert sniff_image_kind(b"") is None


def test_inspect_dims_and_animation_flags() -> None:
    assert inspect_image(_png()).width == 32
    assert inspect_image(_jpeg()).height == 16
    assert inspect_image(_gif()).animated is False
    assert inspect_image(_gif(animated=True)).animated is True
    assert inspect_image(_webp_vp8x(animated=True)).animated is True
    assert inspect_image(_webp_vp8x(animated=False)).animated is False
    assert inspect_image(_webp_vp8l()).ext == ".webp"
    assert inspect_image(_jpeg()).ext == ".jpeg"


def test_needs_file_lane_prefers_magic_over_suffix(tmp_path: Path) -> None:
    odd = tmp_path / "scan.bin"
    odd.write_bytes(_png())
    assert needs_file_lane(str(odd)) is True
    named = tmp_path / "photo.jpg"
    named.write_text("just words", encoding="utf-8")
    assert needs_file_lane(str(named)) is True
    tiff = tmp_path / "scan.tiff"
    tiff.write_bytes(b"II*\x00" + b"\x00" * 32)
    assert needs_file_lane(str(tiff)) is True
    text = tmp_path / "doc.txt"
    text.write_text("plain words", encoding="utf-8")
    assert needs_file_lane(str(text)) is False
    assert needs_file_lane(str(tmp_path / "missing.png")) is False
    link = tmp_path / "link.png"
    link.symlink_to(odd)
    assert needs_file_lane(str(link)) is False


def test_prepare_png_normalizes_odd_extension(tmp_path: Path) -> None:
    raw = _png()
    target = tmp_path / "scan.bin"
    target.write_bytes(raw)
    with prepare_file_inputs(str(target)) as prep:
        assert prep.kind == "image"
        assert prep.suffix == ".png"
        assert prep.source_sha256 == hashlib.sha256(raw).hexdigest()
        assert len(prep.staged) == 1
        assert prep.staged[0].suffix == ".png"
        assert prep.staged[0].read_bytes() == raw
        assert stat.S_IMODE(os.stat(prep.staged[0]).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(prep.root).st_mode) == 0o700
        staged_root = prep.root
    assert not staged_root.exists()
    assert target.read_bytes() == raw


def test_prepare_native_roundtrip(tmp_path: Path) -> None:
    cases = [
        (_jpeg(), "shot.jpg", ".jpeg"),
        (_gif(), "anim.gif", ".gif"),
        (_webp_vp8(), "pic.webp", ".webp"),
        (_webp_vp8l(), "flat.webp", ".webp"),
        (_webp_vp8x(), "movie.webp", ".webp"),
        (_png(), "upper.PNG", ".png"),
    ]
    for raw, name, ext in cases:
        target = tmp_path / name
        target.write_bytes(raw)
        with prepare_file_inputs(str(target)) as prep:
            assert prep.suffix == ext
            assert prep.staged[0].name == "source" + ext
            assert prep.source_sha256 == hashlib.sha256(raw).hexdigest()
        assert not prep.root.exists()


def test_prepare_blocks_executable_even_as_jpg(tmp_path: Path) -> None:
    target = tmp_path / "evil.jpg"
    target.write_bytes(b"MZ\x90\x00fake-pe-body")
    with pytest.raises(FileInputError) as caught, prepare_file_inputs(str(target)):
        pass
    assert caught.value.code == "executable_rejected"
    assert caught.value.manual is False
    prog = tmp_path / "run.exe"
    prog.write_bytes(_png())
    with pytest.raises(FileInputError) as caught2, prepare_file_inputs(str(prog)):
        pass
    assert caught2.value.code == "executable_rejected"


def test_prepare_rejects_bad_magic_with_image_suffix(tmp_path: Path) -> None:
    target = tmp_path / "photo.jpg"
    target.write_bytes(b"hello not an image at all")
    with pytest.raises(FileInputError) as caught, prepare_file_inputs(str(target)):
        pass
    assert caught.value.code == "image_unreadable"


def test_prepare_rejects_decompression_bomb_headers(tmp_path: Path) -> None:
    wide = tmp_path / "wide.png"
    wide.write_bytes(_png(width=20000, height=16))
    with pytest.raises(FileInputError) as caught, prepare_file_inputs(str(wide)):
        pass
    assert caught.value.code == "image_unreadable"
    huge = tmp_path / "huge.png"
    huge.write_bytes(_png(width=8000, height=8000))
    with pytest.raises(FileInputError) as caught2, prepare_file_inputs(str(huge)):
        pass
    assert caught2.value.code == "image_unreadable"


def test_prepare_tiff_is_manual_without_ocr(tmp_path: Path) -> None:
    target = tmp_path / "scan.tif"
    target.write_bytes(b"II*\x00" + b"\x00" * 64)
    with pytest.raises(FileInputError) as caught, prepare_file_inputs(str(target)):
        pass
    assert caught.value.code == "tiff_unsupported"
    assert caught.value.manual is True


def test_prepare_rejects_symlink_oversize_special(tmp_path: Path) -> None:
    real = tmp_path / "real.png"
    real.write_bytes(_png())
    link = tmp_path / "link.png"
    link.symlink_to(real)
    with pytest.raises(FileInputError) as caught, prepare_file_inputs(str(link)):
        pass
    assert caught.value.code == "symlink_rejected"
    big = tmp_path / "big.png"
    with open(big, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024))
    with pytest.raises(FileInputError) as caught2, prepare_file_inputs(str(big)):
        pass
    assert caught2.value.code == "oversized_input"
    with pytest.raises(FileInputError), prepare_file_inputs("/dev/null"):
        pass


def test_prepare_pdf_two_pages_mocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "scan.pdf"
    target.write_bytes(b"%PDF-1.4\n%\xe2\xe3\nfake-body")
    seen: list[list[str]] = []

    def _fake(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen.append(list(cmd))
        assert kwargs.get("capture_output") is True
        if cmd[0] == "pdfinfo":
            return _completed(b"Title: x\nPages: 2\nEncrypted:   no\n")
        assert cmd[:3] == ["pdftoppm", "-png", "-f"]
        prefix = cmd[-1]
        for page in (1, 2):
            Path(prefix + f"-{page}.png").write_bytes(_png())
        return _completed(b"")

    monkeypatch.setattr(file_inputs_mod.subprocess, "run", _fake)
    with prepare_file_inputs(str(target)) as prep:
        assert prep.kind == "pdf"
        assert prep.suffix == ".pdf"
        assert len(prep.staged) == 2
        assert all(p.suffix == ".png" for p in prep.staged)
        assert prep.source_sha256 == hashlib.sha256(target.read_bytes()).hexdigest()
    assert not prep.root.exists()
    assert seen[0][0] == "pdfinfo"
    assert seen[1][0] == "pdftoppm"
    assert "-scale-to" in seen[1]


def test_prepare_pdf_three_pages_never_truncates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "long.pdf"
    target.write_bytes(b"%PDF-1.4\n%\xe2\xe3\nfake-body")
    calls: list[list[str]] = []

    def _fake(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(list(cmd))
        return _completed(b"Pages: 3\nEncrypted: no\n")

    monkeypatch.setattr(file_inputs_mod.subprocess, "run", _fake)
    with pytest.raises(FileInputError) as caught, prepare_file_inputs(str(target)):
        pass
    assert caught.value.code == "file_page_limit"
    assert caught.value.manual is True
    assert [c[0] for c in calls] == ["pdfinfo"]


def test_prepare_pdf_tool_failures_stay_manual_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "scan.pdf"
    target.write_bytes(b"%PDF-1.4\n%\xe2\xe3\nfake-body")

    def _encrypted(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return _completed(b"Pages: 1\nEncrypted: yes (print:yes copy:yes change:yes)\n")

    monkeypatch.setattr(file_inputs_mod.subprocess, "run", _encrypted)
    with pytest.raises(FileInputError) as caught, prepare_file_inputs(str(target)):
        pass
    assert caught.value.code == "encrypted_pdf"

    def _timeout(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd, 20.0)

    monkeypatch.setattr(file_inputs_mod.subprocess, "run", _timeout)
    with pytest.raises(FileInputError) as caught2, prepare_file_inputs(str(target)):
        pass
    assert caught2.value.code == "pdf_unreadable"
