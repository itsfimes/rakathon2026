from __future__ import annotations

import html
import io
import re
import zipfile

from rakathon_backend.converter.archive_security import (
    member_bytes_dangerous,
    member_name_dangerous,
    sniff_executable_bytes,
)
from rakathon_backend.converter.detect import readability_ratio

ZIP_MAX_MEMBERS = 32
ZIP_MAX_EXPANDED = 8 * 1024 * 1024
ZIP_MAX_MEMBER = 1 * 1024 * 1024
ZIP_MAX_RATIO = 64
MIN_TEXT_CHARS = 8


class ArchiveError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _ok_ratio(text: str) -> bool:
    return len(text.strip()) >= MIN_TEXT_CHARS and readability_ratio(text) >= 0.2


def _reject_member(name: str, info_size: int, compress_size: int) -> None:
    if member_name_dangerous(name):
        raise ArchiveError("executable_rejected", "archive carries executables")
    if info_size > ZIP_MAX_MEMBER:
        raise ArchiveError("member_too_large", "archive member exceeds the size cap")


def zip_member_texts(raw: bytes) -> list[str]:
    if sniff_executable_bytes(raw):
        raise ArchiveError("executable_rejected", "archive carries an executable signature")
    bio = io.BytesIO(raw)
    if not zipfile.is_zipfile(bio):
        raise ArchiveError("zip_rejected", "not a zip archive")
    bio.seek(0)
    out: list[str] = []
    expanded = 0
    with zipfile.ZipFile(bio) as zf:
        infos = zf.infolist()
        if len(infos) > ZIP_MAX_MEMBERS:
            raise ArchiveError("zip_too_many", "archive carries too many members")
        for info in infos[:ZIP_MAX_MEMBERS]:
            if info.is_dir():
                continue
            if member_name_dangerous(info.filename):
                raise ArchiveError("executable_rejected", "archive carries executables")
            if info.file_size > ZIP_MAX_MEMBER:
                continue
            if info.compress_size > 0 and info.file_size > info.compress_size * ZIP_MAX_RATIO:
                raise ArchiveError("zip_bomb_rejected", "archive compression ratio is unsafe")
            if expanded + info.file_size > ZIP_MAX_EXPANDED:
                break
            try:
                data = zf.read(info.filename)
            except (OSError, ValueError, RuntimeError):
                continue
            if member_bytes_dangerous(data):
                raise ArchiveError("executable_rejected", "archive member is executable")
            expanded += len(data)
            if b"\x00" in data[:4096]:
                continue
            for charset in ("utf-8", "utf-16", "cp1250"):
                try:
                    decoded = data.decode(charset)
                except (UnicodeDecodeError, ValueError):
                    continue
                if _ok_ratio(decoded):
                    out.append(f"[member {info.filename}]\n{decoded.strip()[:8000]}")
                    break
    if not out:
        raise ArchiveError("zip_no_text", "archive carries no readable member text")
    return out


def xlsx_texts(raw: bytes) -> list[str]:
    if sniff_executable_bytes(raw):
        raise ArchiveError("executable_rejected", "workbook carries an executable signature")
    bio = io.BytesIO(raw)
    if not zipfile.is_zipfile(bio):
        raise ArchiveError("xlsx_rejected", "not an xlsx workbook")
    bio.seek(0)
    texts: list[str] = []
    with zipfile.ZipFile(bio) as zf:
        names = [n for n in zf.namelist() if n.startswith("xl/") and n.endswith(".xml")]
        if len(zf.infolist()) > ZIP_MAX_MEMBERS:
            raise ArchiveError("zip_too_many", "workbook carries too many members")
        for name in names[:ZIP_MAX_MEMBERS]:
            if member_name_dangerous(name):
                raise ArchiveError("executable_rejected", "workbook carries executables")
            try:
                info = zf.getinfo(name)
            except KeyError:
                continue
            if info.file_size > ZIP_MAX_MEMBER:
                continue
            try:
                data = zf.read(name)
            except (OSError, ValueError, RuntimeError):
                continue
            if member_bytes_dangerous(data):
                raise ArchiveError("executable_rejected", "workbook member is executable")
            try:
                decoded = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if "<!doctype" in decoded.lower() or "<!entity" in decoded.lower():
                continue
            inner = re.sub(r"(?s)<[^>]+>", " ", decoded)
            cleaned = html.unescape(re.sub(r"\s+", " ", inner)).strip()
            if _ok_ratio(cleaned):
                texts.append(f"[sheet {name}]\n{cleaned[:8000]}")
            if len(texts) >= 8:
                break
    if not texts:
        raise ArchiveError("xlsx_no_text", "workbook carries no readable text")
    return texts
