from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.converter.adaptive import (
    AdaptiveError,
    AdaptiveManual,
    adapt_bytes,
)
from rakathon_backend.converter.detect import fingerprint_for
from rakathon_backend.converter.planner import (
    RecipeCache,
    metadata_for,
    parse_recipe_strict,
    planner_prompt,
    sample_for_prompt,
)


def test_charset_cp1250_decodes() -> None:
    raw = "syntetický záznam SYN-9 ordinace".encode("cp1250")
    out = adapt_bytes(raw, ".hl7", "note.hl7")
    assert "SYN-9" in out.text
    assert out.new_format is True


def test_xml_safe_rejects_dtd() -> None:
    raw = b'<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY x "y">]><a>hello world ab</a>'
    with pytest.raises((AdaptiveManual, AdaptiveError)):
        adapt_bytes(raw, ".xmldata", "evil.xmldata")


def test_xml_plain_extracts() -> None:
    raw = b'<?xml version="1.0"?><report><line>synthetic summary SYN-2 ward</line></report>'
    out = adapt_bytes(raw, ".xmldata", "r.xmldata")
    assert "synthetic summary" in out.text


def test_html_strips_active_elements() -> None:
    raw = (
        b"<html><head><script>alert(1)</script></head><body><p>clinic note SYN-3</p></body></html>"
    )
    out = adapt_bytes(raw, ".htmldoc", "n.htmldoc")
    assert "clinic note" in out.text
    assert "alert" not in out.text


def test_rtf_limited_text() -> None:
    raw = b"{\\rtf1\\ansi plain synthetic rtf content SYN-4 ward note}"
    out = adapt_bytes(raw, ".rtfdoc", "n.rtfdoc")
    assert "synthetic rtf content" in out.text


def test_hl7_segments_kept() -> None:
    raw = b"MSH|^~\\&|APP|FAC|REC|FAC|20240101||ORU^R01|1|P|2.5\nPID|1||SYN-5||Doe\n"
    out = adapt_bytes(raw, ".hl7", "lab.hl7")
    assert "MSH|" in out.text


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_zip_bounded_member_text() -> None:
    raw = _zip_bytes({"note.txt": b"synthetic member text SYN-6 ward round"})
    out = adapt_bytes(raw, ".zipx", "a.zipx")
    assert "synthetic member text" in out.text


def test_zip_nested_executable_rejected() -> None:
    raw = _zip_bytes({"run.exe": b"MZ\x90\x00binary-body"})
    with pytest.raises((AdaptiveManual, AdaptiveError)) as caught:
        adapt_bytes(raw, ".zipx", "a.zipx")
    assert getattr(caught.value, "code", "") == "executable_rejected"


def test_xlsx_bounded_sheet_text() -> None:
    sheet = (
        b'<?xml version="1.0"?><worksheet><sheetData><row><c><v>102</v></c>'
        b"<c><t>synthetic glucose SYN-7</t></c></row></sheetData></worksheet>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
        zf.writestr("[Content_Types].xml", b"<Types></Types>")
    out = adapt_bytes(buf.getvalue(), ".xlsxdata", "w.xlsxdata")
    assert "synthetic glucose" in out.text


def test_executable_suffix_rejected_with_benign_bytes() -> None:
    with pytest.raises(AdaptiveError) as caught:
        adapt_bytes(b"totally benign text here", ".exe", "run.exe")
    assert caught.value.code == "executable_rejected"


def test_renamed_executable_magic_rejected() -> None:
    with pytest.raises(AdaptiveError) as caught:
        adapt_bytes(b"\x7fELF\x02binary", ".txtdata", "report.txtdata")
    assert caught.value.code == "executable_rejected"


def test_empty_unknown_not_false_conversion(tmp_path: Path) -> None:
    _ = tmp_path
    with pytest.raises(AdaptiveError):
        adapt_bytes(b"", ".unk", "e.unk")
    with pytest.raises(AdaptiveManual):
        adapt_bytes(b"\x00\x01\x02\x03\x04\x05\x06\x07", ".unk", "e.unk")


def test_planner_recipe_strict_allows_only_dsl() -> None:
    good = parse_recipe_strict(
        json.dumps(
            {"version": 1, "steps": [{"op": "charset", "charset": "cp1250", "maxChars": 5000}]}
        )
    )
    assert good["steps"][0]["charset"] == "cp1250"
    for bad in (
        '{"version":1,"steps":[{"op":"exec","cmd":"rm"}]}',
        '{"version":1,"steps":[]}',
        '{"version":1,"steps":[{"op":"charset","charset":"latin9","maxChars":99}]}',
        "```json {}```",
    ):
        with pytest.raises((ValueError, TypeError)):
            parse_recipe_strict(bad)


def test_recipe_executes_and_caches_without_phi(tmp_path: Path) -> None:
    raw = b"ordinace code SYN-8 text with several readable words"
    recipe: dict[str, Any] = {
        "version": 1,
        "steps": [{"op": "charset", "charset": "utf-8", "maxChars": 5000}],
    }
    out = adapt_bytes(raw, ".note", "n.note", recipe=recipe)
    assert "SYN-8" in out.text
    cache_file = tmp_path / "recipes.json"
    cache = RecipeCache(cache_file)
    cache.put(out.fingerprint, recipe)
    stored = cache_file.read_text(encoding="utf-8")
    assert "SYN-8" not in stored
    assert "n.note" not in stored
    hit = cache.get(out.fingerprint)
    assert hit is not None
    again = adapt_bytes(raw, ".note", "other.note", recipe=hit, recipe_reuse=True)
    assert again.recipe_reuse is True


def test_cache_guard_no_false_hit_same_shape() -> None:
    raw_good = b"readable synthetic ward note SYN-10 with words"
    fp = fingerprint_for(raw_good, ".note")
    cache = RecipeCache(None)
    cache.put(
        fp, {"version": 1, "steps": [{"op": "charset", "charset": "utf-8", "maxChars": 5000}]}
    )
    raw_bad = b"\x00\x01\x02\x03\x04\x05"
    with pytest.raises((AdaptiveManual, AdaptiveError)):
        adapt_bytes(raw_bad, ".note", "x.note", recipe=cache.get(fp), recipe_reuse=True)


def test_planner_prompt_carries_no_raw_values() -> None:
    raw = b"Patient John Smith SYN-11 secret note"
    meta = metadata_for(raw, ".note", "fp123", "text")
    prompt = planner_prompt(meta, sample_for_prompt(raw))
    assert "allowedOps" in prompt
    assert "charset" in prompt
