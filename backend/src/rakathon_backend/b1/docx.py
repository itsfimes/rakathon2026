from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

from rakathon_backend.common.blob_store import DOCX_MIME, MAX_BLOB_BYTES

MAX_DOCX_ENTRIES = 128
MAX_DOCX_ENTRY_BYTES = 524_288
MAX_DOCX_TOTAL_BYTES = 1_048_576
MAX_DOCX_TEXT_BYTES = 65_536
DOCUMENT_PATH = "word/document.xml"
RELS_PATH = "word/_rels/document.xml.rels"
CHUNK_BYTES = 65_536
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DANGEROUS_SUBSTRINGS = ("vbaproject", "activex", "embeddings")
_DANGEROUS_SUFFIXES = (".exe", ".bat", ".cmd", ".ps1", ".js", ".vbs", ".jar", ".com", ".scr")


class DocxError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ExtractedDocx:
    text: str
    source_sha256: str
    paragraphs: int
    tables: int


def source_urn(source_sha256: str) -> str:
    return f"urn:sha256:{source_sha256}"


def _fail(code: str, message: str) -> DocxError:
    return DocxError(code, message)


def _check_name(name: str, seen: set[str]) -> None:
    if not name or len(name) > 256:
        raise _fail("docx_entry_rejected", "archive entry name is invalid")
    if name.startswith(("/", "\\")):
        raise _fail("docx_entry_rejected", "archive entry name is invalid")
    if "\\" in name:
        raise _fail("docx_entry_rejected", "archive entry name is invalid")
    if len(name) >= 2 and name[1] == ":":
        raise _fail("docx_entry_rejected", "archive entry name is invalid")
    stripped = name.removesuffix("/")
    for part in stripped.split("/"):
        if part in ("", ".", ".."):
            raise _fail("docx_entry_rejected", "archive entry name is invalid")
    if name in seen:
        raise _fail("docx_entry_rejected", "archive carries duplicate entry names")
    seen.add(name)
    lowered = name.lower()
    for marker in _DANGEROUS_SUBSTRINGS:
        if marker in lowered:
            raise _fail("docx_entry_rejected", "archive carries a dangerous entry")
    for suffix in _DANGEROUS_SUFFIXES:
        if lowered.endswith(suffix):
            raise _fail("docx_entry_rejected", "archive carries a dangerous entry")


def _reject_active_content(raw: bytes) -> None:
    probe = raw.replace(b"\x00", b"").lower()
    if b"<!doctype" in probe or b"<!entity" in probe:
        raise _fail("docx_dtd_rejected", "document XML carries active content")


def _parse_xml(raw: bytes, limit: int) -> Any:
    if len(raw) > limit:
        raise _fail("docx_too_large", "document XML part exceeds the size cap")
    _reject_active_content(raw)
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise _fail("docx_xml_invalid", "document XML is not well formed") from exc


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _check_relationships(raw: bytes) -> None:
    root = _parse_xml(raw, MAX_DOCX_ENTRY_BYTES)
    for node in root.iter():
        if _local(str(node.tag)) != "Relationship":
            continue
        target = str(node.attrib.get("Target", "")).strip()
        mode = str(node.attrib.get("TargetMode", "")).strip().lower()
        lowered = target.lower()
        if mode == "external":
            raise _fail("docx_external_rejected", "document carries external relationships")
        if lowered.startswith(("http://", "https://", "ftp://", "file:", "mailto:")):
            raise _fail("docx_external_rejected", "document carries external relationships")


def _para_text(para: Any) -> tuple[str, bool]:
    parts: list[str] = []
    for node in para.iter():
        if _local(str(node.tag)) == "t":
            parts.append(node.text or "")
    style = ""
    ppr = para.find(f"{W_NS}pPr")
    if ppr is not None:
        pstyle = ppr.find(f"{W_NS}pStyle")
        if pstyle is not None:
            style = str(pstyle.attrib.get(f"{W_NS}val", ""))
    return ("".join(parts), style.lower().startswith("heading"))


def _cell_text(cell: Any) -> str:
    paras: list[str] = []
    for node in cell.iter():
        if _local(str(node.tag)) != "p":
            continue
        text, _ = _para_text(node)
        if text:
            paras.append(text)
    return " ".join(paras)


def _extract_body_text(root: Any) -> tuple[str, int, int]:
    body = root.find(f"{W_NS}body")
    if body is None:
        raise _fail("docx_xml_invalid", "document has no body")
    lines: list[str] = []
    paragraphs = 0
    tables = 0
    for child in body:
        kind = _local(str(child.tag))
        if kind == "p":
            text, heading = _para_text(child)
            if text.strip():
                lines.append(f"# {text}" if heading else text)
                paragraphs += 1
        elif kind == "tbl":
            tables += 1
            for row in child.iter():
                if _local(str(row.tag)) != "tr":
                    continue
                cells = [n for n in row if _local(str(n.tag)) == "tc"]
                lines.append(" | ".join(_cell_text(c) for c in cells))
            lines.append("")
    text = "\n".join(lines).strip()
    if len(text.encode("utf-8")) > MAX_DOCX_TEXT_BYTES:
        raise _fail("docx_too_large", "extracted text exceeds the size cap")
    return (text, paragraphs, tables)


def extract_docx_text(data: bytes) -> ExtractedDocx:
    if len(data) > MAX_BLOB_BYTES:
        raise _fail("docx_too_large", "document exceeds the size cap")
    if len(data) < 4:
        raise _fail("docx_invalid", "document is not a readable package")
    digest = hashlib.sha256(data).hexdigest()
    try:
        handle = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise _fail("docx_invalid", "document is not a readable package") from exc
    with handle:
        names = handle.namelist()
        if len(names) > MAX_DOCX_ENTRIES:
            raise _fail("docx_too_large", "archive carries too many entries")
        seen: set[str] = set()
        total = 0
        document_raw: bytes | None = None
        rels_raw: bytes | None = None
        for info in handle.infolist():
            name = info.filename
            _check_name(name, seen)
            if name.endswith("/"):
                continue
            if info.flag_bits & 0x1:
                raise _fail("docx_encrypted", "document is encrypted")
            lowered = name.lower()
            if lowered == "encryptedpackage" or "[dataspaces/" in lowered:
                raise _fail("docx_encrypted", "document is encrypted")
            if info.file_size > MAX_DOCX_ENTRY_BYTES:
                raise _fail("docx_too_large", "archive entry exceeds the size cap")
            if info.compress_size > MAX_BLOB_BYTES:
                raise _fail("docx_too_large", "archive entry exceeds the size cap")
            collected = bytearray()
            with handle.open(info, mode="r") as stream:
                while True:
                    chunk = stream.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_DOCX_TOTAL_BYTES:
                        raise _fail("docx_too_large", "archive expands beyond the size cap")
                    if len(collected) + len(chunk) > MAX_DOCX_ENTRY_BYTES + 1:
                        raise _fail("docx_too_large", "archive entry exceeds the size cap")
                    if name in (DOCUMENT_PATH, RELS_PATH):
                        collected += chunk
            if name == DOCUMENT_PATH:
                document_raw = bytes(collected)
            elif name == RELS_PATH:
                rels_raw = bytes(collected)
    if document_raw is None:
        raise _fail("docx_invalid", "document has no readable body")
    if rels_raw is not None:
        _check_relationships(rels_raw)
    root = _parse_xml(document_raw, MAX_DOCX_ENTRY_BYTES)
    text, paragraphs, tables = _extract_body_text(root)
    _ = DOCX_MIME
    return ExtractedDocx(text=text, source_sha256=digest, paragraphs=paragraphs, tables=tables)
