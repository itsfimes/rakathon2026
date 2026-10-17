from __future__ import annotations

import hashlib
import os
import shutil
import stat
import struct
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from rakathon_backend.converter.detect import suffix_is_executable
from rakathon_backend.converter.extract import MAX_RAW_BYTES, sniff_executable

MAX_FILE_PAGES = 2
MAX_PREVIEW_PIXELS = 2000
MAX_PREVIEW_BYTES = 5 * 1024 * 1024
MAX_PREVIEW_TOTAL = 10 * 1024 * 1024
MAX_IMAGE_DIMENSION = 10000
MAX_IMAGE_PIXELS = 25000000
PDF_INFO_TIMEOUT = 10.0
PDF_RENDER_TIMEOUT = 20.0
NATIVE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})
TIFF_SUFFIXES = frozenset({".tiff", ".tif"})


class FileInputError(ValueError):
    def __init__(self, code: str, message: str, *, manual: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.manual = manual


@dataclass(frozen=True, slots=True)
class ImageInfo:
    kind: str
    width: int
    height: int
    animated: bool
    ext: str


@dataclass(slots=True)
class PreparedFileInput:
    original: Path
    source_sha256: str
    suffix: str
    filename: str
    kind: str
    staged: list[Path]
    root: Path
    animated: bool = False


def sniff_image_kind(raw: bytes) -> str | None:
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(raw) >= 3 and raw[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    if raw[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    return None


def needs_file_lane(raw_path: str) -> bool:
    path = Path(raw_path)
    try:
        if path.is_symlink():
            return False
        with open(path, "rb") as handle:
            head = handle.read(16)
    except OSError:
        return False
    if not head:
        return False
    if sniff_image_kind(head) is not None:
        return True
    return path.suffix.lower() in NATIVE_SUFFIXES | TIFF_SUFFIXES


def _check_dims(width: int, height: int) -> tuple[int, int]:
    if not 1 <= width <= MAX_IMAGE_DIMENSION:
        raise FileInputError("image_unreadable", "image dimensions are outside the limit")
    if not 1 <= height <= MAX_IMAGE_DIMENSION:
        raise FileInputError("image_unreadable", "image dimensions are outside the limit")
    if width * height > MAX_IMAGE_PIXELS:
        raise FileInputError("image_unreadable", "image pixel count is outside the limit")
    return (width, height)


def _png_dims(raw: bytes) -> tuple[int, int]:
    if len(raw) < 24 or raw[12:16] != b"IHDR":
        raise FileInputError("image_unreadable", "png header is missing its dimensions")
    width = struct.unpack(">I", raw[16:20])[0]
    height = struct.unpack(">I", raw[20:24])[0]
    return _check_dims(width, height)


def _jpeg_dims(raw: bytes) -> tuple[int, int]:
    pos = 2
    for _ in range(256):
        if pos + 2 > len(raw) or raw[pos] != 0xFF:
            raise FileInputError("image_unreadable", "jpeg markers are unreadable")
        marker = raw[pos + 1]
        pos += 2
        while marker == 0xFF:
            if pos >= len(raw):
                raise FileInputError("image_unreadable", "jpeg markers are unreadable")
            marker = raw[pos]
            pos += 1
        if marker in (0x00, 0xD9, 0xDA):
            raise FileInputError("image_unreadable", "jpeg carries no dimension header")
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        if pos + 2 > len(raw):
            raise FileInputError("image_unreadable", "jpeg markers are unreadable")
        seg_len = struct.unpack(">H", raw[pos : pos + 2])[0]
        if seg_len < 2 or pos + seg_len > len(raw):
            raise FileInputError("image_unreadable", "jpeg markers are unreadable")
        if marker in (0xC4, 0xC8, 0xCC) or not 0xC0 <= marker <= 0xCF:
            pos += seg_len
            continue
        if seg_len < 7:
            raise FileInputError("image_unreadable", "jpeg carries no dimension header")
        height = struct.unpack(">H", raw[pos + 3 : pos + 5])[0]
        width = struct.unpack(">H", raw[pos + 5 : pos + 7])[0]
        return _check_dims(width, height)
    raise FileInputError("image_unreadable", "jpeg carries no dimension header")


def _gif_info(raw: bytes) -> ImageInfo:
    if len(raw) < 10:
        raise FileInputError("image_unreadable", "gif header is truncated")
    w, h = _check_dims(struct.unpack("<H", raw[6:8])[0], struct.unpack("<H", raw[8:10])[0])
    return ImageInfo(kind="gif", width=w, height=h, animated=b"NETSCAPE" in raw, ext=".gif")


def _webp_info(raw: bytes) -> ImageInfo:
    if len(raw) < 16:
        raise FileInputError("image_unreadable", "webp header is truncated")
    fourcc = raw[12:16]
    if fourcc == b"VP8 ":
        if len(raw) < 30 or raw[23:26] != b"\x9d\x01\x2a":
            raise FileInputError("image_unreadable", "webp bitstream is unreadable")
        vw = struct.unpack("<H", raw[26:28])[0] & 0x3FFF
        vh = struct.unpack("<H", raw[28:30])[0] & 0x3FFF
        w, h = _check_dims(vw, vh)
        return ImageInfo(kind="webp", width=w, height=h, animated=False, ext=".webp")
    if fourcc == b"VP8L":
        if len(raw) < 25 or raw[20] != 0x2F:
            raise FileInputError("image_unreadable", "webp bitstream is unreadable")
        bits = struct.unpack("<I", raw[21:25])[0]
        w, h = _check_dims((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        return ImageInfo(kind="webp", width=w, height=h, animated=False, ext=".webp")
    if fourcc == b"VP8X":
        if len(raw) < 30:
            raise FileInputError("image_unreadable", "webp bitstream is unreadable")
        vw = int.from_bytes(raw[24:27], "little") + 1
        vh = int.from_bytes(raw[27:30], "little") + 1
        w, h = _check_dims(vw, vh)
        return ImageInfo(kind="webp", width=w, height=h, animated=bool(raw[20] & 0x02), ext=".webp")
    raise FileInputError("image_unreadable", "webp chunk is not a supported still")


def inspect_image(raw: bytes) -> ImageInfo:
    kind = sniff_image_kind(raw)
    if kind == "png":
        width, height = _png_dims(raw)
        return ImageInfo(kind="png", width=width, height=height, animated=False, ext=".png")
    if kind == "jpeg":
        width, height = _jpeg_dims(raw)
        return ImageInfo(kind="jpeg", width=width, height=height, animated=False, ext=".jpeg")
    if kind == "gif":
        return _gif_info(raw)
    if kind == "webp":
        return _webp_info(raw)
    raise FileInputError("image_unreadable", "image bytes carry no native magic")


def _pdf_page_count(path: Path) -> int:
    try:
        proc = subprocess.run(
            ["pdfinfo", str(path)],
            capture_output=True,
            timeout=PDF_INFO_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FileInputError("pdf_unreadable", "pdf info tool failed") from exc
    if proc.returncode != 0 or len(proc.stdout) > 65536:
        raise FileInputError("malformed_pdf", "pdf info tool rejected the file")
    try:
        text = proc.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FileInputError("malformed_pdf", "pdf info output is unreadable") from exc
    pages = 0
    for line in text.splitlines():
        head, _, tail = line.partition(":")
        key = head.strip().lower()
        if key == "encrypted" and tail.strip().lower() != "no":
            raise FileInputError("encrypted_pdf", "pdf is encrypted")
        if key == "pages":
            try:
                pages = int(tail.strip().split()[0])
            except (ValueError, IndexError):
                pages = 0
    if pages < 1:
        raise FileInputError("malformed_pdf", "pdf carries no pages")
    if pages > MAX_FILE_PAGES:
        raise FileInputError("file_page_limit", "pdf exceeds the two page lane cap", manual=True)
    return pages


def _render_pdf(path: Path, root: Path, pages: int) -> list[Path]:
    prefix = root / "page"
    try:
        proc = subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-f",
                "1",
                "-l",
                str(pages),
                "-scale-to",
                str(MAX_PREVIEW_PIXELS),
                str(path),
                str(prefix),
            ],
            capture_output=True,
            timeout=PDF_RENDER_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FileInputError("pdf_unreadable", "pdf render exceeded its budget") from exc
    if proc.returncode != 0 or len(proc.stdout) > 65536:
        raise FileInputError("pdf_unreadable", "pdf render failed")
    staged: list[Path] = []
    total = 0
    for index in range(1, pages + 1):
        candidate = root / f"page-{index}.png"
        try:
            data = candidate.read_bytes()
        except OSError as exc:
            raise FileInputError("pdf_unreadable", "pdf render produced no preview") from exc
        if not data or len(data) > MAX_PREVIEW_BYTES:
            raise FileInputError("pdf_unreadable", "pdf preview exceeds the per file cap")
        if sniff_image_kind(data) != "png":
            raise FileInputError("pdf_unreadable", "pdf preview is not a native image")
        _png_dims(data)
        total += len(data)
        if total > MAX_PREVIEW_TOTAL:
            raise FileInputError("pdf_unreadable", "pdf previews exceed the total cap")
        try:
            os.chmod(candidate, 0o600)
        except OSError as exc:
            raise FileInputError("pdf_unreadable", "pdf preview cannot be secured") from exc
        staged.append(candidate)
    return staged


def _stage_image(raw: bytes, found: ImageInfo, root: Path) -> Path:
    target = root / ("source" + found.ext)
    try:
        target.write_bytes(raw)
        os.chmod(target, 0o600)
    except OSError as exc:
        raise FileInputError("staging_failed", "validated image cannot be staged") from exc
    return target


@contextmanager
def prepare_file_inputs(raw_path: str) -> Iterator[PreparedFileInput]:
    path = Path(raw_path)
    if path.is_symlink():
        raise FileInputError("symlink_rejected", "input path is a symlink")
    try:
        info = path.stat()
    except OSError as exc:
        raise FileInputError("unreadable_input", "input file cannot be read") from exc
    if not stat.S_ISREG(info.st_mode):
        raise FileInputError("special_file_rejected", "input is not a regular file")
    if info.st_size > MAX_RAW_BYTES:
        raise FileInputError("oversized_input", "input exceeds the raw size cap")
    if info.st_size == 0:
        raise FileInputError("empty_input", "input file is empty")
    suffix = path.suffix.lower()
    if suffix_is_executable(suffix):
        raise FileInputError("executable_rejected", "executable suffix is rejected")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FileInputError("unreadable_input", "input file cannot be read") from exc
    if len(raw) > MAX_RAW_BYTES:
        raise FileInputError("oversized_input", "input exceeds the raw size cap")
    if not raw:
        raise FileInputError("empty_input", "input file is empty")
    if sniff_executable(raw):
        raise FileInputError("executable_rejected", "input carries an executable signature")
    digest = hashlib.sha256(raw).hexdigest()
    tmp = tempfile.mkdtemp(prefix="rakathon-file-")
    try:
        os.chmod(tmp, 0o700)
        root = Path(tmp)
        if raw[:5] == b"%PDF-":
            count = _pdf_page_count(path)
            staged = _render_pdf(path, root, count)
            yield PreparedFileInput(
                original=path,
                source_sha256=digest,
                suffix=".pdf",
                filename=path.name,
                kind="pdf",
                staged=staged,
                root=root,
            )
        else:
            kind = sniff_image_kind(raw)
            if kind == "tiff" or (kind is None and suffix in TIFF_SUFFIXES):
                raise FileInputError("tiff_unsupported", "tiff needs human review", manual=True)
            if kind is None:
                if suffix in NATIVE_SUFFIXES:
                    raise FileInputError("image_unreadable", "image suffix carries no native magic")
                raise FileInputError("not_file_lane", "input is not a native file lane candidate")
            found = inspect_image(raw)
            target = _stage_image(raw, found, root)
            yield PreparedFileInput(
                original=path,
                source_sha256=digest,
                suffix=found.ext,
                filename=path.name,
                kind="image",
                staged=[target],
                root=root,
                animated=found.animated,
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
