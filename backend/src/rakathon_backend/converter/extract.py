from __future__ import annotations

import hashlib
import re
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rakathon_backend.b1.docx import DocxError, extract_docx_text
from rakathon_backend.common.blob_store import MAX_BLOB_BYTES
from rakathon_backend.converter.adaptive import AdaptiveError as _AdaptiveError
from rakathon_backend.converter.adaptive import AdaptiveManual as _AdaptiveManual
from rakathon_backend.converter.adaptive import adapt_bytes as _adapt_bytes
from rakathon_backend.converter.detect import suffix_is_executable

MAX_RAW_BYTES = 5 * 1024 * 1024
MAX_EXTRACT_BYTES = 60 * 1024
MAX_PDF_PAGES = 20
PDF_TOOL_TIMEOUT = 20.0
ALLOWED_SUFFIXES = frozenset({".docx", ".txt", ".json", ".csv", ".pdf"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tiff", ".tif"})
_MRN_RE = re.compile(r"MRN:\s*([A-Za-z0-9][A-Za-z0-9\-]{0,63})")
_EXEC_MAGICS = (
    b"\x7fELF",
    b"MZ",
    b"\xcf\xfa\xed\xfe",
    b"\xce\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"#!",
)


class ConverterError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ManualReviewNeeded(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class Extracted:
    text: str
    pages: tuple[str, ...]
    source_sha256: str
    extract_sha256: str
    suffix: str
    filename: str


def sniff_executable(raw: bytes) -> bool:
    return any(raw.startswith(magic) for magic in _EXEC_MAGICS)


def hash_only(raw_path: str) -> tuple[str, str] | None:
    path = Path(raw_path)
    if path.is_symlink():
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_RAW_BYTES:
        return None
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(65536)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return None
    return (digest.hexdigest(), path.name)


def detect_identity_conflict(text: str) -> tuple[bool, list[str]]:
    seen: list[str] = []
    for match in _MRN_RE.finditer(text):
        value = match.group(1).strip()
        if value and value not in seen:
            seen.append(value)
    return (len(seen) > 1, seen)


def _label_pages(pages: list[str]) -> str:
    return "\n".join(f"[page {i + 1}]\n{page}".rstrip() for i, page in enumerate(pages))


def _finish(pages: list[str], raw: bytes, suffix: str, filename: str) -> Extracted:
    text = _label_pages(pages)
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_EXTRACT_BYTES:
        raise ConverterError("extract_too_large", "extracted text exceeds the size cap")
    if not text.strip():
        raise ConverterError("empty_text", "document carries no readable text")
    return Extracted(
        text=text,
        pages=tuple(pages),
        source_sha256=hashlib.sha256(raw).hexdigest(),
        extract_sha256=hashlib.sha256(encoded).hexdigest(),
        suffix=suffix,
        filename=filename,
    )


def _validate_path(raw_path: str) -> tuple[Path, str]:
    path = Path(raw_path)
    if path.is_symlink():
        raise ConverterError("symlink_rejected", "input path is a symlink")
    try:
        st = path.stat()
    except OSError as exc:
        raise ConverterError("unreadable_input", "input file cannot be read") from exc
    if not stat.S_ISREG(st.st_mode):
        raise ConverterError("special_file_rejected", "input is not a regular file")
    if st.st_size > MAX_RAW_BYTES:
        raise ConverterError("oversized_input", "input exceeds the raw size cap")
    if st.st_size == 0:
        raise ConverterError("empty_input", "input file is empty")
    suffix = path.suffix.lower()
    if suffix_is_executable(suffix):
        raise ConverterError("executable_rejected", "executable suffix is rejected")
    if suffix in IMAGE_SUFFIXES:
        raise ManualReviewNeeded("image_no_ocr", "image input needs human transcription")
    return (path, suffix)


Decoder = Callable[[bytes, Path], Extracted]

DECODERS: dict[str, Decoder] = {}


def decoder(suffix: str) -> Callable[[Decoder], Decoder]:
    def _register(func: Decoder) -> Decoder:
        DECODERS[suffix] = func
        return func

    return _register


@decoder(".docx")
def _decode_docx(raw: bytes, path: Path) -> Extracted:
    if len(raw) > MAX_BLOB_BYTES:
        raise ConverterError("oversized_input", "docx input exceeds the package size cap")
    try:
        out = extract_docx_text(raw)
    except DocxError as exc:
        raise ConverterError(exc.code, exc.message) from exc
    if not out.text.strip():
        raise ConverterError("empty_text", "document carries no readable text")
    return _finish([out.text.strip()], raw, ".docx", path.name)


@decoder(".txt")
@decoder(".json")
@decoder(".csv")
def _decode_textlike(raw: bytes, path: Path) -> Extracted:
    if b"\x00" in raw:
        raise ConverterError("binary_text_rejected", "text input carries binary data")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConverterError("binary_text_rejected", "text input is not valid UTF-8") from exc
    if not decoded.strip():
        raise ConverterError("empty_text", "document carries no readable text")
    return _finish([decoded.strip()], raw, path.suffix.lower(), path.name)


def _pdf_info(path: Path) -> int:
    try:
        proc = subprocess.run(
            ["pdfinfo", str(path)],
            capture_output=True,
            timeout=PDF_TOOL_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConverterError("pdf_unreadable", "pdf info tool failed") from exc
    if proc.returncode != 0:
        raise ConverterError("malformed_pdf", "pdf info tool rejected the file")
    try:
        info = proc.stdout.decode("utf-8", "replace")
    except ValueError as exc:
        raise ConverterError("malformed_pdf", "pdf info output is unreadable") from exc
    for line in info.splitlines():
        head, _, tail = line.partition(":")
        if head.strip().lower() == "encrypted" and tail.strip().lower() != "no":
            raise ConverterError("encrypted_pdf", "pdf is encrypted")
    pages = 0
    for line in info.splitlines():
        if line.strip().lower().startswith("pages:"):
            try:
                pages = int(line.split(":", 1)[1].strip().split()[0])
            except (ValueError, IndexError):
                pages = 0
    if pages < 1:
        raise ConverterError("malformed_pdf", "pdf carries no pages")
    if pages > MAX_PDF_PAGES:
        raise ConverterError("oversized_input", "pdf exceeds the page cap")
    return pages


def _pdf_page_text(path: Path, page: int) -> str:
    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(path), "-"],
            capture_output=True,
            timeout=PDF_TOOL_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConverterError("pdf_unreadable", "pdf text tool failed") from exc
    if proc.returncode != 0:
        raise ConverterError("malformed_pdf", "pdf text extraction failed")
    try:
        return proc.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConverterError("malformed_pdf", "pdf text layer is not valid UTF-8") from exc


def _extract_pdf(raw: bytes, path: Path) -> Extracted:
    if raw[:5] != b"%PDF-":
        raise ConverterError("malformed_pdf", "pdf magic bytes are missing")
    pages = _pdf_info(path)
    texts = [_pdf_page_text(path, i + 1).strip() for i in range(pages)]
    if not any(text.strip() for text in texts):
        raise ManualReviewNeeded("scan_no_ocr", "pdf has no text layer for human review")
    return _finish([text for text in texts], raw, ".pdf", path.name)


DECODERS[".pdf"] = _extract_pdf


def extract_file(raw_path: str) -> Extracted:
    path, suffix = _validate_path(raw_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConverterError("unreadable_input", "input file cannot be read") from exc
    if len(raw) > MAX_RAW_BYTES:
        raise ConverterError("oversized_input", "input exceeds the raw size cap")
    if not raw:
        raise ConverterError("empty_input", "input file is empty")
    if sniff_executable(raw):
        raise ConverterError("executable_rejected", "input carries an executable signature")
    decode = DECODERS.get(suffix)
    if decode is not None:
        try:
            return decode(raw, path)
        except ConverterError as exc:
            if exc.code != "binary_text_rejected" or b"\x00" in raw:
                raise
    try:
        adapted = _adapt_bytes(raw, suffix, path.name)
    except _AdaptiveManual as exc:
        raise ManualReviewNeeded(exc.code, exc.message) from exc
    except _AdaptiveError as exc:
        raise ConverterError(exc.code, exc.message) from exc
    return Extracted(
        text=adapted.text,
        pages=adapted.pages,
        source_sha256=adapted.source_sha256,
        extract_sha256=adapted.extract_sha256,
        suffix=adapted.suffix,
        filename=adapted.filename,
    )
