from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest
from docx_samples import make_docx

from rakathon_backend.converter.extract import (
    MAX_EXTRACT_BYTES,
    MAX_RAW_BYTES,
    ConverterError,
    ManualReviewNeeded,
    detect_identity_conflict,
    extract_file,
    hash_only,
    sniff_executable,
)

FIXTURES = Path(__file__).with_name("fixtures") / "converter"


def _gold() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads((FIXTURES / "gold.json").read_text()))


def test_fixture_hashes_match_recorded_sums() -> None:
    sums = (FIXTURES / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert len(sums) == 3
    for line in sums:
        digest, name = line.split(None, 1)
        data = (FIXTURES / name.strip()).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest


def test_lab_pdf_pages_and_gold_fields() -> None:
    out = extract_file(str(FIXTURES / "fixture_01_lab_report.pdf"))
    assert len(out.pages) == 1
    assert out.suffix == ".pdf"
    for value in ("ZEBRA", "SYN-000001", "TST^GLU-F", "102", "mg/dL"):
        assert value in out.text
    assert "[page 1]" in out.text


def test_discharge_pdf_two_pages_stable_hash() -> None:
    first = extract_file(str(FIXTURES / "fixture_02_discharge_narrative.pdf"))
    second = extract_file(str(FIXTURES / "fixture_02_discharge_narrative.pdf"))
    assert len(first.pages) == 2
    assert "[page 2]" in first.text
    assert "SYN-000002" in first.pages[0] and "SYN-000002" in first.pages[1]
    assert first.source_sha256 == second.source_sha256
    assert first.extract_sha256 == second.extract_sha256


def test_tricky_pdf_conflict_detected_deterministically() -> None:
    out = extract_file(str(FIXTURES / "fixture_03_ambiguity_conflict.pdf"))
    conflict, values = detect_identity_conflict(out.text)
    assert conflict is True
    assert values == ["SYN-000003", "SYN-000099"]
    assert "03/04/05" in out.text


def test_consistent_identity_has_no_conflict() -> None:
    out = extract_file(str(FIXTURES / "fixture_01_lab_report.pdf"))
    conflict, values = detect_identity_conflict(out.text)
    assert conflict is False
    assert values == ["SYN-000001"]


def test_gold_fixture_names_exist() -> None:
    gold = _gold()
    assert isinstance(gold, dict)
    assert len(str(gold)) > 100


def test_textlike_inputs_accepted(tmp_path: Path) -> None:
    for suffix in (".txt", ".json", ".csv"):
        target = tmp_path / f"doc{suffix}"
        target.write_text("plain synthetic line SYN-1", encoding="utf-8")
        out = extract_file(str(target))
        assert out.suffix == suffix
        assert "plain synthetic line" in out.text


def test_docx_input_uses_existing_extractor(tmp_path: Path) -> None:
    assert MAX_RAW_BYTES == 5 * 1024 * 1024
    raw = make_docx([("p", "synthetic docx line SYN-9")])
    target = tmp_path / "doc.docx"
    target.write_bytes(raw)
    out = extract_file(str(target))
    assert out.suffix == ".docx"
    assert "synthetic docx line" in out.text


def _minimal_pdf(*, with_text: bool) -> bytes:
    content = b"BT /F1 12 Tf 72 700 Td (hello SYN) Tj ET" if with_text else b""
    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(data))
        data += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 6\n0000000000 65535 f \n"
    for off in offsets:
        data += f"{off:010d} 00000 n \n".encode()
    data += b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n"
    return bytes(data)


def test_scan_pdf_without_text_layer_needs_review(tmp_path: Path) -> None:
    target = tmp_path / "scan.pdf"
    target.write_bytes(_minimal_pdf(with_text=False))
    with pytest.raises(ManualReviewNeeded) as caught:
        extract_file(str(target))
    assert caught.value.code == "scan_no_ocr"


def test_truncated_pdf_rejected(tmp_path: Path) -> None:
    target = tmp_path / "bad.pdf"
    target.write_bytes(b"%PDF-1.4\nnot a real body")
    with pytest.raises(ConverterError):
        extract_file(str(target))


def test_not_a_pdf_magic_rejected(tmp_path: Path) -> None:
    target = tmp_path / "fake.pdf"
    target.write_bytes(b"definitely not pdf content here")
    with pytest.raises(ConverterError) as caught:
        extract_file(str(target))
    assert caught.value.code == "malformed_pdf"


def test_unknown_suffix_uses_adaptive_decoders(tmp_path: Path) -> None:
    target = tmp_path / "data.zip"
    target.write_bytes(b"PK fake archive with readable synthetic words SYN-1")
    out = extract_file(str(target))
    assert "readable synthetic words" in out.text
    blob = tmp_path / "blob.unknownext"
    blob.write_bytes(b"\x00\x01\x02\x03\x04\x05\x06\x07binary")
    with pytest.raises((ConverterError, ManualReviewNeeded)):
        extract_file(str(blob))


def test_image_suffix_needs_manual_review(tmp_path: Path) -> None:
    for suffix in (".png", ".jpg", ".tiff"):
        target = tmp_path / f"scan{suffix}"
        target.write_bytes(b"\x89PNG fake image bytes")
        with pytest.raises(ManualReviewNeeded) as caught:
            extract_file(str(target))
        assert caught.value.code == "image_no_ocr"


def test_binary_text_rejected(tmp_path: Path) -> None:
    target = tmp_path / "bin.txt"
    target.write_bytes(b"hello\x00binary")
    with pytest.raises(ConverterError) as caught:
        extract_file(str(target))
    assert caught.value.code == "binary_text_rejected"


def test_empty_text_rejected(tmp_path: Path) -> None:
    target = tmp_path / "empty.txt"
    target.write_text("   \n  ", encoding="utf-8")
    with pytest.raises(ConverterError) as caught:
        extract_file(str(target))
    assert caught.value.code == "empty_text"


def test_symlink_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real.txt"
    real.write_text("content", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    with pytest.raises(ConverterError) as caught:
        extract_file(str(link))
    assert caught.value.code == "symlink_rejected"


def test_special_file_rejected() -> None:
    with pytest.raises(ConverterError) as caught:
        extract_file("/dev/null")
    assert caught.value.code in ("special_file_rejected", "empty_input")


def test_oversize_rejected(tmp_path: Path) -> None:
    target = tmp_path / "big.txt"
    with open(target, "wb") as handle:
        handle.write(b"x" * (5 * 1024 * 1024 + 1))
    with pytest.raises(ConverterError) as caught:
        extract_file(str(target))
    assert caught.value.code == "oversized_input"


def test_extract_cap_enforced() -> None:
    assert MAX_EXTRACT_BYTES == 60 * 1024


def test_executable_signatures_rejected_despite_renamed_suffix(tmp_path: Path) -> None:
    samples = {
        "report.pdf": b"\x7fELF\x02\x01\x01\x00fake-elf-body",
        "notes.txt": b"MZ\x90\x00fake-pe-body",
        "data.csv": b"#!/bin/sh\necho pwned\n",
        "scan.pdf": b"\xcf\xfa\xed\xfefake-macho",
    }
    for name, body in samples.items():
        target = tmp_path / name
        target.write_bytes(body)
        with pytest.raises(ConverterError) as caught:
            extract_file(str(target))
        assert caught.value.code == "executable_rejected"


def test_sniff_executable_helpers() -> None:
    assert sniff_executable(b"\x7fELFrest") is True
    assert sniff_executable(b"MZrest") is True
    assert sniff_executable(b"#!/usr/bin/env python\n") is True
    assert sniff_executable(b"%PDF-1.4 rest") is False
    assert sniff_executable(b"plain text") is False


def test_hash_only_fingerprints_without_parsing(tmp_path: Path) -> None:
    target = tmp_path / "weird.bin"
    target.write_bytes(b"\x00\x01\x02binary")
    out = hash_only(str(target))
    assert out is not None
    digest, name = out
    assert name == "weird.bin"
    assert digest == hashlib.sha256(b"\x00\x01\x02binary").hexdigest()


def test_hash_only_refuses_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.txt"
    real.write_text("x", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    assert hash_only(str(link)) is None
    assert hash_only(str(tmp_path / "missing.txt")) is None
