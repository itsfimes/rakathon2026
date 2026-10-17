from __future__ import annotations

import io as _io
import zipfile as _zf
from pathlib import Path

from rakathon_backend.converter.detect import magic_category

SAFE_SUFFIXES = frozenset({".pdf", ".docx", ".txt", ".json", ".csv"})


def looks_like_docx(raw: bytes) -> bool:
    if raw[:4] != b"PK\x03\x04":
        return False
    try:
        bio = _io.BytesIO(raw)
        if not _zf.is_zipfile(bio):
            return False
        bio.seek(0)
        with _zf.ZipFile(bio) as zf:
            names = [name.lower() for name in zf.namelist()[:32]]
    except (OSError, ValueError, RuntimeError, _zf.BadZipFile, NotImplementedError):
        return False
    return "word/document.xml" in names and "[content_types].xml" in names


def safe_suffix(filename: str, raw: bytes) -> str:
    low = Path(filename).name.lower()
    dot = low.rfind(".")
    cand = low[dot:] if dot >= 0 else ""
    if cand in SAFE_SUFFIXES and cand != ".docx":
        return cand
    category, _magic = magic_category(raw)
    if category == "pdf":
        return ".pdf"
    if looks_like_docx(raw):
        return ".docx"
    if cand and len(cand) <= 16 and all(c.isalnum() or c in (".-") for c in cand):
        if cand == ".docx":
            return ".bin"
        return cand if cand.startswith(".") else ".bin"
    return ".bin"
