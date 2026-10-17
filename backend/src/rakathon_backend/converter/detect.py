from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

from rakathon_backend.converter.archive_security import (
    EXEC_MAGICS,
    EXEC_SUFFIXES,
    MACRO_TOKENS,
    fingerprint_material,
    member_name_dangerous,
)

ATTEMPT_CODES = frozenset(
    {
        "known_bypass",
        "charset_utf8",
        "charset_utf16",
        "charset_cp1250",
        "xml_safe",
        "html_strip",
        "xlsx_bounded",
        "rtf_text",
        "zip_members",
        "hl7_text",
        "planner_recipe",
        "planner_fallback",
        "cache_reuse",
        "rejected_executable",
        "rejected_encrypted",
        "rejected_binary",
        "manual_review",
    }
)
ARCHIVE_MIMES = frozenset({"zip", "xlsx", "docx"})
_READABILITY_RE = re.compile(r"[A-Za-z]{2,}")


@dataclass(frozen=True, slots=True)
class AttemptEvent:
    code: str
    status: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Detected:
    category: str
    magic: str
    suffix: str
    fingerprint: str
    encrypted_hint: bool


def sniff_executable_bytes(raw: bytes) -> bool:
    return any(raw.startswith(m) for m in EXEC_MAGICS)


def suffix_is_executable(suffix: str) -> bool:
    return suffix.lower() in EXEC_SUFFIXES


def magic_category(raw: bytes) -> tuple[str, str]:
    if raw[:4] == b"\x7fELF":
        return ("executable", "elf")
    if raw[:2] == b"MZ":
        return ("executable", "mz")
    if raw[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
        return ("executable", "macho")
    if raw[:2] == b"#!":
        return ("executable", "shebang")
    if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return ("ole", "ole")
    if raw[:5] == b"%PDF-":
        return ("pdf", "pdf")
    if raw[:4] == b"PK\x03\x04":
        return ("zip", "zip")
    if raw[:5] == b"{\\rtf":
        return ("rtf", "rtf")
    if raw[:1] in (b"<",) and b"<html" in raw[:2048].lower():
        return ("html", "html")
    if raw[:1] == b"<" and b"<?xml" in raw[:512].lower():
        return ("xml", "xml")
    if b"\x00" in raw[:4096]:
        return ("binary", "nul")
    return ("text", "plain")


def structural_root(raw: bytes, limit: int = 512) -> str:
    head = raw[:limit].lower()
    if head.startswith(b"<?xml"):
        end = head.find(b">", 0, 256)
        tag = b"xml-decl" if end >= 0 else b"xml"
        return tag.decode("ascii", "replace")
    if head.lstrip().startswith(b"<"):
        match = re.match(rb"<\s*([a-zA-Z][\w:.-]{0,63})", head.lstrip()[:128])
        if match:
            try:
                return "tag:" + match.group(1).decode("ascii", "replace").lower()[:64]
            except ValueError:
                return "tag:unknown"
        return "tag:unknown"
    if b"MSH|" in head[:256]:
        return "hl7-msh"
    return "flat"


def fingerprint_for(raw: bytes, suffix: str) -> str:
    category, magic = magic_category(raw)
    root = structural_root(raw)
    member_hint = "none"
    if category == "zip":
        member_hint = zip_member_hint(raw)
    return fingerprint_material(category, magic, root, member_hint, suffix)


def zip_member_hint(raw: bytes, cap: int = 8) -> str:
    try:
        bio = io.BytesIO(raw[: 2 * 1024 * 1024])
        if not zipfile.is_zipfile(bio):
            return "notzip"
        bio.seek(0)
        with zipfile.ZipFile(bio) as zf:
            names = zf.namelist()[:cap]
            kinds: list[str] = []
            for name in names:
                low = name.lower()
                if low.endswith(".xml"):
                    kinds.append("xml")
                elif low.endswith(".txt"):
                    kinds.append("txt")
                elif low.endswith(".rels"):
                    kinds.append("rels")
                else:
                    kinds.append("other")
            return "+".join(kinds) if kinds else "empty"
    except (OSError, ValueError, RuntimeError):
        return "unreadable"


def archive_has_danger(raw: bytes) -> bool:
    try:
        bio = io.BytesIO(raw[: 8 * 1024 * 1024])
        if not zipfile.is_zipfile(bio):
            return False
        bio.seek(0)
        with zipfile.ZipFile(bio) as zf:
            for info in zf.infolist()[:64]:
                if member_name_dangerous(info.filename):
                    return True
                if info.file_size > 20 * 1024 * 1024:
                    return True
                if info.compress_size > 0 and info.file_size > info.compress_size * 64:
                    return True
    except (OSError, ValueError, RuntimeError):
        return False
    lowered = raw[: 64 * 1024].lower()
    return any(tok.encode() in lowered for tok in MACRO_TOKENS)


def readability_ratio(text: str) -> float:
    if not text.strip():
        return 0.0
    words = text.split()
    if not words:
        return 0.0
    good = sum(1 for w in words[:2000] if _READABILITY_RE.search(w))
    return good / max(1, min(len(words), 2000))


def ole_carries_encrypted_marker(raw: bytes, limit: int = 8192) -> bool:
    compact = raw[:limit].replace(b"\x00", b"").lower()
    return b"encrypt" in compact


def detect(raw: bytes, suffix: str, filename: str) -> Detected:
    category, magic = magic_category(raw)
    fp = fingerprint_for(raw, suffix)
    enc = raw[: 2 * 1024].lower().find(b"encrypt") >= 0 and category in ("pdf", "zip")
    if category == "ole" and ole_carries_encrypted_marker(raw):
        enc = True
    _ = filename
    return Detected(
        category=category, magic=magic, suffix=suffix, fingerprint=fp, encrypted_hint=enc
    )
