from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from rakathon_backend.b5.opencode.file_client import MAX_FILES
from rakathon_backend.b5.opencode.validation import MAX_RESPONSE_BYTES
from rakathon_backend.converter.extract import MAX_EXTRACT_BYTES, Extracted

TRANSCRIPT_MAX_BYTES = MAX_RESPONSE_BYTES
TRANSCRIPT_MAX_PAGES = MAX_FILES
TRANSCRIPT_MAX_ISSUES = 16
TRANSCRIPT_ISSUE_CODES = frozenset(
    {
        "unreadable",
        "partial",
        "low_confidence",
        "handwriting",
        "glare_blur",
        "truncated",
        "blank_page",
    }
)


class TranscriptionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    pages: tuple[str, ...]
    issues: tuple[str, ...]
    raw: str


def build_transcription_prompt(page_count: int) -> str:
    if isinstance(page_count, bool) or not isinstance(page_count, int):
        raise TypeError("page count is outside the limit")
    if not 1 <= page_count <= TRANSCRIPT_MAX_PAGES:
        raise ValueError("page count is outside the limit")
    codes = ", ".join(sorted(TRANSCRIPT_ISSUE_CODES))
    return (
        "Transcribe each document image into strict JSON, reading pages in order. "
        "Copy only text that is visibly present, keeping units, dates, names and "
        "identifiers verbatim. Never invent, normalize or reorder content. "
        "Leave the text of an unreadable page empty and flag it in issues. "
        "Respond with ONLY a JSON object, no prose, no markdown fences, "
        'with exactly these keys: {"pages": [{"page": 1, "text": "..."}], '
        '"issues": [...]}. Pages must be exactly '
        + str(page_count)
        + " entries numbered from 1 in order with no gaps, "
        "no duplicates and no extra keys. Issues holds zero or more of: " + codes + "."
    )


def _reject_constant(value: str) -> Any:
    raise ValueError("non-finite constant is rejected: " + value[:8])


def _has_control(text: str) -> bool:
    for char in text:
        point = ord(char)
        if point == 0x7F or 0x80 <= point <= 0x9F:
            return True
        if point < 0x20 and char not in ("\n", "\t"):
            return True
    return False


def parse_transcription(raw_text: str, *, page_count: int) -> TranscriptionResult:
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise TranscriptionError("transcript_bad_json", "transcription output is unusable")
    if len(raw_text.encode("utf-8")) > TRANSCRIPT_MAX_BYTES:
        raise TranscriptionError(
            "transcript_too_large", "transcription output exceeds the size cap"
        )
    if isinstance(page_count, bool) or not isinstance(page_count, int):
        raise TranscriptionError(
            "transcript_page_mismatch", "transcription page count does not match the input"
        )
    if not 1 <= page_count <= TRANSCRIPT_MAX_PAGES:
        raise TranscriptionError(
            "transcript_page_mismatch", "transcription page count does not match the input"
        )
    try:
        parsed: Any = json.loads(raw_text, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise TranscriptionError("transcript_bad_json", "transcription output is unusable") from exc
    if not isinstance(parsed, dict) or set(parsed.keys()) != {"pages", "issues"}:
        raise TranscriptionError(
            "transcript_bad_shape", "transcription output has an unexpected shape"
        )
    pages_raw: Any = parsed["pages"]
    issues_raw: Any = parsed["issues"]
    if not isinstance(pages_raw, list) or len(pages_raw) != page_count:
        raise TranscriptionError(
            "transcript_page_mismatch", "transcription page count does not match the input"
        )
    if not isinstance(issues_raw, list) or len(issues_raw) > TRANSCRIPT_MAX_ISSUES:
        raise TranscriptionError(
            "transcript_bad_shape", "transcription output has an unexpected shape"
        )
    issues: list[str] = []
    for item in issues_raw:
        if not isinstance(item, str) or item not in TRANSCRIPT_ISSUE_CODES:
            raise TranscriptionError(
                "transcript_bad_shape", "transcription output has an unexpected shape"
            )
        issues.append(item)
    pages: list[str] = []
    for index, entry in enumerate(pages_raw):
        if not isinstance(entry, dict) or set(entry.keys()) != {"page", "text"}:
            raise TranscriptionError(
                "transcript_bad_shape", "transcription output has an unexpected shape"
            )
        number: Any = entry["page"]
        if isinstance(number, bool) or not isinstance(number, int) or number != index + 1:
            raise TranscriptionError(
                "transcript_page_mismatch",
                "transcription page count does not match the input",
            )
        text: Any = entry["text"]
        if not isinstance(text, str) or _has_control(text):
            raise TranscriptionError(
                "transcript_bad_shape", "transcription output has an unexpected shape"
            )
        pages.append(text)
    total = sum(len(item.encode("utf-8")) for item in pages)
    if total > MAX_EXTRACT_BYTES:
        raise TranscriptionError(
            "transcript_too_large", "transcription output exceeds the size cap"
        )
    if not any(item.strip() for item in pages):
        raise TranscriptionError("transcript_no_text", "transcription carries no readable text")
    return TranscriptionResult(pages=tuple(pages), issues=tuple(issues), raw=raw_text)


def build_extracted(
    pages: tuple[str, ...] | list[str],
    *,
    source_sha256: str,
    suffix: str,
    filename: str,
) -> Extracted:
    ordered = list(pages)
    if not ordered or not any(item.strip() for item in ordered):
        raise TranscriptionError("transcript_no_text", "transcription carries no readable text")
    text = "\n".join(f"[page {index + 1}]\n{page}".rstrip() for index, page in enumerate(ordered))
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_EXTRACT_BYTES:
        raise TranscriptionError(
            "transcript_too_large", "transcription output exceeds the size cap"
        )
    if not text.strip():
        raise TranscriptionError("transcript_no_text", "transcription carries no readable text")
    return Extracted(
        text=text,
        pages=tuple(ordered),
        source_sha256=source_sha256,
        extract_sha256=hashlib.sha256(encoded).hexdigest(),
        suffix=suffix,
        filename=filename,
    )
