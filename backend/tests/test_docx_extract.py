from __future__ import annotations

import io
import zipfile

import pytest
from docx_samples import MARKER, make_docx

from rakathon_backend.b1.docx import (
    DocxError,
    extract_docx_text,
    source_urn,
)


def test_paragraphs_tables_order_and_boundaries() -> None:
    raw = make_docx(
        [
            ("p", f"first {MARKER} line"),
            ("t", [["a1", "b1"], ["a2", "b2"]]),
            ("p", "last line"),
        ]
    )
    out = extract_docx_text(raw)
    assert MARKER in out.text
    first = out.text.index("first")
    row = out.text.index("a1 | b1")
    last = out.text.index("last line")
    assert first < row < last
    assert "a2 | b2" in out.text
    assert out.paragraphs == 2
    assert out.tables == 1


def test_heading_text_preserved_with_marker() -> None:
    raw = make_docx([("p", f"chapter {MARKER}", "Heading1"), ("p", "body")])
    out = extract_docx_text(raw)
    assert f"chapter {MARKER}" in out.text
    assert out.text.index("#") < out.text.index("body")


def test_source_hash_and_urn_are_stable() -> None:
    raw = make_docx([("p", "stable text")])
    first = extract_docx_text(raw)
    second = extract_docx_text(raw)
    assert first.source_sha256 == second.source_sha256
    assert len(first.source_sha256) == 64
    assert source_urn(first.source_sha256) == f"urn:sha256:{first.source_sha256}"


def test_internal_relationships_are_followed_never() -> None:
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://example.org/styles" Target="word/styles.xml"/>'
        "</Relationships>"
    )
    raw = make_docx([("p", "plain")], rels_xml=rels)
    out = extract_docx_text(raw)
    assert out.text == "plain"


def test_doctype_ascii_rejected() -> None:
    evil = (
        b'<?xml version="1.0"?><!DOCTYPE w:document [<!ENTITY x "y">]>'
        b'<w:document xmlns:w="urn:x"><w:body/></w:document>'
    )
    with pytest.raises(DocxError) as caught:
        extract_docx_text(_wrap(evil))
    assert caught.value.code == "docx_dtd_rejected"


def test_doctype_utf16_bypass_rejected() -> None:
    evil = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<!DOCTYPE w:document [<!ENTITY x "y">]>'
        f'<w:document xmlns:w="urn:x"><w:body><w:p><w:r><w:t>{MARKER}</w:t></w:r></w:p>'
        "</w:body></w:document>"
    ).encode("utf-16")
    with pytest.raises(DocxError) as caught:
        extract_docx_text(_wrap(evil))
    assert caught.value.code == "docx_dtd_rejected"


def test_entity_declaration_rejected() -> None:
    evil = (
        b'<?xml version="1.0"?><w:document xmlns:w="urn:x">'
        b'<!ENTITY greeting "hello">'
        b"<w:body/></w:document>"
    )
    with pytest.raises(DocxError) as caught:
        extract_docx_text(_wrap(evil))
    assert caught.value.code == "docx_dtd_rejected"


def test_invalid_xml_rejected() -> None:
    with pytest.raises(DocxError) as caught:
        extract_docx_text(_wrap(b"<w:document><w:body><oops"))
    assert caught.value.code == "docx_xml_invalid"


def test_missing_body_rejected() -> None:
    raw = make_docx([], document_override=b"<w:document/>")
    with pytest.raises(DocxError):
        extract_docx_text(raw)


def test_error_messages_carry_no_document_text() -> None:
    secret = f"secret-{MARKER}"
    evil = (
        f'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x "{secret}">]>'
        "<w:document><w:body/></w:document>"
    ).encode()
    with pytest.raises(DocxError) as caught:
        extract_docx_text(_wrap(evil))
    assert MARKER not in str(caught.value)
    assert MARKER not in caught.value.code


def _wrap(document_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("word/document.xml", document_bytes)
    return buf.getvalue()
