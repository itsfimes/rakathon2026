from __future__ import annotations

import io
import random
import warnings
import zipfile

import pytest
from docx_samples import MARKER, make_docx, rels_xml

from rakathon_backend.b1.docx import DocxError, extract_docx_text
from rakathon_backend.common.blob_store import (
    DOCX_MIME,
    BlobStore,
    BlobTooLarge,
    BlobUnsupportedType,
)


def _zip(entries: list[tuple[str, bytes]], *, encrypted: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as handle, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for name, data in entries:
            handle.writestr(name, data)
    raw = buf.getvalue()
    if encrypted is not None:
        raw = _set_encrypted_flag(raw, encrypted)
    return raw


def _set_encrypted_flag(raw: bytes, name: str) -> bytes:
    out = bytearray(raw)
    marker = b"PK\x01\x02"
    found = False
    start = 0
    while True:
        idx = bytes(out).find(marker, start)
        if idx == -1:
            break
        name_len = int.from_bytes(bytes(out[idx + 28 : idx + 30]), "little")
        entry_name = bytes(out[idx + 46 : idx + 46 + name_len]).decode("utf-8", "replace")
        if entry_name == name:
            out[idx + 8] |= 0x01
            found = True
            break
        start = idx + 4
    assert found, "central entry missing"
    return bytes(out)


def _doc(*, text: str = "ok") -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="urn:x">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    ).encode()


@pytest.mark.parametrize("name", ["../evil.xml", "/abs.xml", "word\\evil.xml", "C:evil.xml"])
def test_traversal_and_absolute_names_rejected(name: str) -> None:
    raw = _zip([("word/document.xml", _doc()), (name, b"x")])
    with pytest.raises(DocxError) as caught:
        extract_docx_text(raw)
    assert caught.value.code == "docx_entry_rejected"
    assert MARKER not in str(caught.value)


def test_duplicate_names_rejected() -> None:
    raw = _zip([("word/document.xml", _doc()), ("word/document.xml", _doc())])
    with pytest.raises(DocxError) as caught:
        extract_docx_text(raw)
    assert caught.value.code == "docx_entry_rejected"


def test_encrypted_entry_rejected() -> None:
    raw = _zip([("word/document.xml", _doc())], encrypted="word/document.xml")
    with pytest.raises(DocxError) as caught:
        extract_docx_text(raw)
    assert caught.value.code == "docx_encrypted"


def test_encrypted_package_marker_rejected() -> None:
    raw = _zip([("word/document.xml", _doc()), ("EncryptedPackage", b"x")])
    with pytest.raises(DocxError) as caught:
        extract_docx_text(raw)
    assert caught.value.code == "docx_encrypted"


def test_macro_and_embedded_entries_rejected() -> None:
    for name in ("word/vbaProject.bin", "word/embeddings/oleObject1.bin", "word/activeX/ax1.bin"):
        raw = _zip([("word/document.xml", _doc()), (name, b"x")])
        with pytest.raises(DocxError) as caught:
            extract_docx_text(raw)
        assert caught.value.code == "docx_entry_rejected"


def test_external_relationship_modes_rejected() -> None:
    for rels in (
        rels_xml("External", "http://example.org/style"),
        rels_xml("", "https://example.org/style"),
    ):
        raw = make_docx([("p", "ok")], rels_xml=rels)
        with pytest.raises(DocxError) as caught:
            extract_docx_text(raw)
        assert caught.value.code == "docx_external_rejected"


def test_per_entry_cap_rejected() -> None:
    big = b"q" * (524_288 + 8)
    raw = make_docx([("p", "ok")], extra=[("word/big.bin", big)])
    with pytest.raises(DocxError) as caught:
        extract_docx_text(raw)
    assert caught.value.code == "docx_too_large"


def test_expanded_total_cap_rejected() -> None:
    rng = random.Random(7)
    chunk = rng.randbytes(400_000)
    raw = make_docx(
        [("p", "ok")],
        extra=[("word/a.bin", chunk), ("word/b.bin", chunk), ("word/c.bin", chunk)],
    )
    with pytest.raises(DocxError) as caught:
        extract_docx_text(raw)
    assert caught.value.code == "docx_too_large"


def test_extracted_text_cap_rejected() -> None:
    items = [("p", f"line {n} " + "w" * 64) for n in range(1200)]
    raw = make_docx(items)
    with pytest.raises(DocxError) as caught:
        extract_docx_text(raw)
    assert caught.value.code == "docx_too_large"


def test_missing_document_rejected() -> None:
    raw = _zip([("word/other.xml", b"<x/>")])
    with pytest.raises(DocxError) as caught:
        extract_docx_text(raw)
    assert caught.value.code == "docx_invalid"


def test_non_zip_rejected() -> None:
    with pytest.raises(DocxError) as caught:
        extract_docx_text(b"%PDF-1.4 fake")
    assert caught.value.code == "docx_invalid"


def test_blob_store_accepts_docx_mime_and_bounds() -> None:
    store = BlobStore()
    raw = make_docx([("p", "hello")])
    ref = store.put(raw, DOCX_MIME)
    assert store.get(ref).content_type == DOCX_MIME
    assert store.delete(ref) is True
    assert store.delete(ref) is False
    with pytest.raises(BlobTooLarge):
        store.put(b"x" * (262_144 + 1), DOCX_MIME)
    with pytest.raises(BlobUnsupportedType):
        store.put(b"x", "application/pdf")
