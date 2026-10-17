from __future__ import annotations

import hashlib
import html
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rakathon_backend.converter.archive import ArchiveError
from rakathon_backend.converter.archive import xlsx_texts as _xlsx_texts
from rakathon_backend.converter.archive import zip_member_texts as _zip_member_texts
from rakathon_backend.converter.archive_security import (
    sniff_executable_bytes,
    suffix_is_executable,
)
from rakathon_backend.converter.detect import (
    AttemptEvent,
    archive_has_danger,
    detect,
    readability_ratio,
)

MAX_RAW_BYTES = 5 * 1024 * 1024
MAX_EXTRACT_BYTES = 60 * 1024
MAX_ATTEMPTS = 5
DECODE_BUDGET_S = 180.0
CHARSETS = ("utf-8", "utf-16", "cp1250")
READABILITY_MIN = 0.35
MIN_TEXT_CHARS = 8


@dataclass(frozen=True, slots=True)
class AdaptiveText:
    text: str
    pages: tuple[str, ...]
    source_sha256: str
    extract_sha256: str
    suffix: str
    filename: str
    attempts: tuple[AttemptEvent, ...]
    fingerprint: str
    recipe_reuse: bool
    new_format: bool
    planner_mode: str


class AdaptiveError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AdaptiveManual(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _finish(pages: list[str], raw: bytes, suffix: str, filename: str) -> tuple[str, str]:
    text = "\n".join(f"[page {i + 1}]\n{p}".rstrip() for i, p in enumerate(pages))
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_EXTRACT_BYTES:
        raise AdaptiveError("extract_too_large", "extracted text exceeds the size cap")
    if not text.strip():
        raise AdaptiveError("empty_text", "document carries no readable text")
    digest = hashlib.sha256(encoded).hexdigest()
    return (text, digest)


def _ok_text(text: str) -> bool:
    cleaned = text.strip()
    if len(cleaned) < MIN_TEXT_CHARS:
        return False
    if "\x00" in text:
        return False
    sample = cleaned[:2000]
    bad = sum(1 for ch in sample if not ch.isprintable() and ch not in ("\n", "\t"))
    if bad > len(sample) // 3:
        return False
    return readability_ratio(cleaned) >= READABILITY_MIN


def _decode_charset(raw: bytes, charset: str) -> str:
    try:
        return raw.decode(charset)
    except (UnicodeDecodeError, ValueError) as exc:
        raise AdaptiveError("charset_failed", f"charset {charset} failed") from exc


def _strip_html(text: str) -> str:
    without_scripts = re.sub(
        r"(?is)<\s*(script|style|object|embed|iframe|form|button|input)[^>]*>.*?"
        r"<\s*/\s*\1\s*>",
        " ",
        text,
    )
    without_tags = re.sub(r"(?s)<[^>]{0,4096}>", " ", without_scripts)
    return html.unescape(re.sub(r"[ \t\x0b\f\r]+", " ", without_tags)).strip()


def _parse_xml_safe(text: str) -> str:
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise AdaptiveError("xml_dtd_rejected", "xml with DTD or entities is rejected")
    if "http://" in lowered or "https://" in lowered:
        outer = re.sub(r"(?is)<\s*(script|style)[^>]*>.*?</\1\s*>", " ", text)
        inner = re.sub(r"(?s)<[^>]+>", " ", outer)
    else:
        inner = re.sub(r"(?s)<[^>]+>", " ", text)
    cleaned = html.unescape(re.sub(r"\s+", " ", inner)).strip()
    if not cleaned:
        raise AdaptiveError("xml_no_text", "xml carries no readable text")
    return cleaned


def _parse_rtf(raw_text: str, limit: int = 60000) -> str:
    text = raw_text[:limit]
    if not text.lstrip().startswith("{\\rtf"):
        raise AdaptiveError("rtf_rejected", "not an rtf document")
    text = re.sub(r"(?s)\{\s*\\\*?\\[^}]*\}", " ", text)
    text = re.sub(r"\\[a-zA-Z]{1,32}\d*\s?", " ", text)
    text = re.sub(r"[{}]", " ", text)
    text = re.sub(r"\\'([0-9a-fA-F]{2})", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _hl7_text(raw_text: str) -> str:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    kept = [ln for ln in lines if re.match(r"^[A-Z0-9]{2,4}\|", ln)]
    if len(kept) < 1:
        raise AdaptiveError("hl7_rejected", "no HL7v2 segments found")
    return "\n".join(kept[:256])


def _call_step(func: Callable[..., str], arg: str) -> str | None:
    try:
        result = func(arg)
    except (AdaptiveError, AdaptiveManual, ValueError, OSError, RuntimeError):
        return None
    if isinstance(result, str) and _ok_text(result):
        return result
    return None


def deterministic_attempts(raw: bytes, detected_category: str) -> tuple[list[str], list[str]]:
    pages: list[str] = []
    tried: list[str] = []
    if detected_category in ("text", "xml", "html", "rtf", "binary"):
        for charset in CHARSETS:
            tried.append(f"charset_{charset.replace('-', '')}")
            try:
                decoded = _decode_charset(raw, charset)
            except AdaptiveError:
                continue
            head = decoded[:200].lower()
            if "msh|" in head:
                got = _call_step(_hl7_text, decoded)
                if got is not None:
                    pages.append(got)
                    break
                continue
            lstripped = decoded.lstrip().lower()
            if lstripped.startswith("<"):
                if "<html" in decoded[:2048].lower():
                    got = _call_step(_strip_html, decoded)
                    if got is not None:
                        pages.append(got)
                        break
                    continue
                try:
                    cleaned = _parse_xml_safe(decoded)
                except AdaptiveError:
                    continue
                if _ok_text(cleaned):
                    pages.append(cleaned[:20000])
                    break
                continue
            if decoded.lstrip().startswith("{\\rtf"):
                try:
                    cleaned = _parse_rtf(decoded)
                except AdaptiveError:
                    continue
                if _ok_text(cleaned):
                    pages.append(cleaned[:20000])
                    break
                continue
            if _ok_text(decoded):
                pages.append(decoded.strip()[:20000])
                break
        return (pages, tried[:MAX_ATTEMPTS])
    if detected_category == "zip":
        tried.append("zip_members")
        try:
            pages.extend(_zip_member_texts(raw))
        except (AdaptiveError, ArchiveError):
            pass
        if not pages:
            tried.append("xlsx_bounded")
            try:
                pages.extend(_xlsx_texts(raw))
            except (AdaptiveError, ArchiveError):
                pass
        return (pages, tried[:MAX_ATTEMPTS])
    return (pages, tried[:MAX_ATTEMPTS])


def execute_recipe_step(raw: bytes, op: str, detail: dict[str, Any]) -> list[str]:
    if op == "charset":
        name = str(detail.get("charset", "utf-8"))
        if name not in CHARSETS:
            raise AdaptiveError("recipe_rejected", "unsupported charset step")
        decoded = _decode_charset(raw, name)
        raw_max = detail.get("maxChars", 20000)
        picked = raw_max if isinstance(raw_max, int) else 20000
        max_chars = max(64, min(picked, 20000))
        if not _ok_text(decoded):
            raise AdaptiveError("recipe_no_text", "recipe step has no readable text")
        return [decoded.strip()[:max_chars]]
    if op == "html_strip":
        decoded = _decode_charset(raw, "utf-8")
        cleaned = _strip_html(decoded)
        if not _ok_text(cleaned):
            raise AdaptiveError("recipe_no_text", "recipe step has no readable text")
        return [cleaned[:20000]]
    if op == "xml_safe":
        decoded = _decode_charset(raw, "utf-8")
        cleaned = _parse_xml_safe(decoded)
        if not _ok_text(cleaned):
            raise AdaptiveError("recipe_no_text", "recipe step has no readable text")
        return [cleaned[:20000]]
    if op == "rtf_text":
        decoded = _decode_charset(raw, "utf-8")
        cleaned = _parse_rtf(decoded)
        if not _ok_text(cleaned):
            raise AdaptiveError("recipe_no_text", "recipe step has no readable text")
        return [cleaned[:20000]]
    if op == "hl7_text":
        decoded = _decode_charset(raw, "utf-8")
        return [_hl7_text(decoded)[:20000]]
    if op == "zip_members":
        try:
            return _zip_member_texts(raw)
        except ArchiveError as exc:
            raise AdaptiveError(exc.code, exc.message) from exc
    if op == "xlsx_bounded":
        try:
            return _xlsx_texts(raw)
        except ArchiveError as exc:
            raise AdaptiveError(exc.code, exc.message) from exc
    raise AdaptiveError("recipe_rejected", f"unknown recipe op {op}")


def adapt_bytes(
    raw: bytes,
    suffix: str,
    filename: str,
    recipe: dict[str, Any] | None = None,
    recipe_reuse: bool = False,
) -> AdaptiveText:
    started = time.monotonic()
    if not raw:
        raise AdaptiveError("empty_input", "input file is empty")
    if len(raw) > MAX_RAW_BYTES:
        raise AdaptiveError("oversized_input", "input exceeds the raw size cap")
    if suffix_is_executable(suffix):
        raise AdaptiveError("executable_rejected", "executable suffix is rejected")
    if sniff_executable_bytes(raw):
        raise AdaptiveError("executable_rejected", "input carries an executable signature")
    detected = detect(raw, suffix, filename)
    if detected.category == "zip" and archive_has_danger(raw):
        raise AdaptiveError("executable_rejected", "archive carries executable or macro content")
    if detected.encrypted_hint:
        raise AdaptiveManual("encrypted_no_extract", "encrypted container needs human review")
    events: list[AttemptEvent] = []
    pages: list[str] = []
    planner_mode = "none"
    if recipe is not None:
        planner_mode = "planner" if not recipe_reuse else "cache"
        steps = recipe.get("steps")
        if isinstance(steps, list):
            for entry in steps[:MAX_ATTEMPTS]:
                if time.monotonic() - started > DECODE_BUDGET_S:
                    break
                if not isinstance(entry, dict):
                    continue
                op = str(entry.get("op", ""))
                try:
                    got = execute_recipe_step(raw, op, entry)
                except (AdaptiveError, AdaptiveManual, ArchiveError):
                    events.append(
                        AttemptEvent(code="planner_recipe", status="failed", detail=op[:48])
                    )
                    continue
                events.append(AttemptEvent(code="planner_recipe", status="ok", detail=op[:48]))
                pages.extend(got)
                if pages:
                    break
    if not pages:
        det_pages, tried = deterministic_attempts(raw, detected.category)
        for code in tried:
            events.append(AttemptEvent(code="planner_fallback", status="tried", detail=code[:48]))
        pages.extend(det_pages)
        if planner_mode == "none":
            planner_mode = "fallback"
    if not pages:
        raise AdaptiveManual(
            "binary_no_extract" if detected.category == "binary" else "unknown_no_extract",
            "no bounded decoder produced readable text",
        )
    text, digest = _finish(pages, raw, suffix, Path(filename).name)
    return AdaptiveText(
        text=text,
        pages=tuple(pages),
        source_sha256=hashlib.sha256(raw).hexdigest(),
        extract_sha256=digest,
        suffix=suffix,
        filename=Path(filename).name,
        attempts=tuple(events[:8]),
        fingerprint=detected.fingerprint,
        recipe_reuse=recipe_reuse,
        new_format=suffix.lower() not in (".docx", ".txt", ".json", ".csv", ".pdf"),
        planner_mode=planner_mode,
    )
