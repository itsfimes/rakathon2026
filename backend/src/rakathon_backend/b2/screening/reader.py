from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import os
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rakathon_backend.b2.screening import schema
from rakathon_backend.common.errors import ContractError

SCREENING_ENV_VAR = "RAKATHON_SCREENING_SOURCE"
SCREENING_MEMBER_ENV_VAR = "RAKATHON_SCREENING_MEMBER"
DEFAULT_MEMBER = "Rakhaton2026.csv"
MAX_SOURCE_BYTES = 512 * 1024 * 1024
INDEX_COMMIT_EVERY = 5000


@dataclass(frozen=True)
class ResolvedSource:
    path: Path
    is_zip: bool
    member: str | None
    size_bytes: int


@dataclass(frozen=True)
class ValidationResult:
    rows: int
    columns: int
    distinct_persons: int
    duplicate_invitations: int
    empty_nullable: dict[str, int]
    cross_mismatches: int
    first_hash: str
    mid_hash: str
    end_hash: str
    stream_digest: str
    source_bytes: int


def resolve_source(explicit: str | None) -> ResolvedSource:
    raw = explicit.strip() if isinstance(explicit, str) and explicit.strip() else ""
    if not raw:
        raw = os.environ.get(SCREENING_ENV_VAR, "").strip()
    if not raw:
        raise ContractError(code="not_configured", message="screening source is not configured")
    target = Path(raw)
    try:
        info = os.lstat(target)
    except OSError as exc:
        raise ContractError(
            code="source_unreadable", message="screening source unreadable"
        ) from exc
    if stat.S_ISLNK(info.st_mode):
        raise ContractError(code="source_unreadable", message="screening source must not link")
    if not stat.S_ISREG(info.st_mode):
        raise ContractError(code="source_unreadable", message="screening source is not a file")
    if info.st_size <= 0 or info.st_size > MAX_SOURCE_BYTES:
        raise ContractError(code="source_too_large", message="screening source size rejected")
    suffix = target.suffix.lower()
    if suffix == ".zip":
        member = os.environ.get(SCREENING_MEMBER_ENV_VAR, "").strip() or DEFAULT_MEMBER
        return ResolvedSource(path=target, is_zip=True, member=member, size_bytes=info.st_size)
    if suffix == ".csv":
        return ResolvedSource(path=target, is_zip=False, member=None, size_bytes=info.st_size)
    raise ContractError(code="source_unsupported", message="screening source must be CSV or ZIP")


def _check_member_name(member: str) -> None:
    if not member or member != member.strip():
        raise ContractError(code="bad_member", message="archive member name rejected")
    if "/" in member or "\\" in member or member.startswith(".") or ".." in member:
        raise ContractError(code="bad_member", message="archive member name rejected")


def _resolve_member(resolved: ResolvedSource, member_override: str | None) -> str:
    member = member_override.strip() if isinstance(member_override, str) else ""
    if not member:
        member = resolved.member or DEFAULT_MEMBER
    _check_member_name(member)
    try:
        archive = zipfile.ZipFile(str(resolved.path), "r")
    except Exception as exc:
        raise ContractError(code="source_unreadable", message="archive unreadable") from exc
    try:
        names = archive.namelist()
    except Exception as exc:
        archive.close()
        raise ContractError(code="source_unreadable", message="archive unreadable") from exc
    if names.count(member) != 1:
        archive.close()
        raise ContractError(code="bad_member", message="archive member not found exactly once")
    try:
        info = archive.getinfo(member)
    except KeyError as exc:
        archive.close()
        raise ContractError(code="bad_member", message="archive member not found") from exc
    if info.is_dir():
        archive.close()
        raise ContractError(code="bad_member", message="archive member is not a file")
    if info.flag_bits & 0x1:
        archive.close()
        raise ContractError(code="bad_member", message="encrypted archives are rejected")
    if info.file_size <= 0 or info.file_size > MAX_SOURCE_BYTES:
        archive.close()
        raise ContractError(code="source_too_large", message="archive member size rejected")
    archive.close()
    return member


def _iter_text(raw: Any) -> Generator[tuple[int, str, dict[str, str]]]:
    text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
    try:
        header: list[str] | None = None
        lineno = 0
        for line in text:
            if not line.strip():
                continue
            lineno += 1
            try:
                fields = next(csv.reader([line]))
            except Exception as exc:
                raise ContractError(code="bad_row", message="csv parse failed") from exc
            if header is None:
                header = fields
                schema.check_header(header)
                continue
            if len(fields) != len(schema.HEADER):
                raise ContractError(code="bad_row", message="row width mismatch")
            yield (lineno - 1, line, dict(zip(schema.HEADER, fields, strict=True)))
    finally:
        text.close()


def iter_raw_lines(
    resolved: ResolvedSource, member_override: str | None = None
) -> Iterator[tuple[int, str, dict[str, str]]]:
    if not resolved.is_zip:
        if member_override is not None:
            raise ContractError(code="bad_member", message="plain CSV takes no member")
        with open(resolved.path, "rb") as raw:
            yield from _iter_text(raw)
        return
    member = _resolve_member(resolved, member_override)
    with zipfile.ZipFile(str(resolved.path), "r") as archive, archive.open(member, "r") as raw:
        yield from _iter_text(raw)


def iter_validated_rows(
    resolved: ResolvedSource, member_override: str | None = None
) -> Generator[tuple[int, dict[str, str]]]:
    for lineno, _line, raw in iter_raw_lines(resolved, member_override):
        try:
            yield (lineno, schema.validate_row(raw))
        except ContractError as exc:
            raise ContractError(code=exc.code, message=f"{exc.message} at row {lineno}") from exc


class _DiskIndex:
    def __init__(self, workdir: str) -> None:
        self._path = str(Path(workdir) / "screening_index.sqlite3")
        self._conn = sqlite3.connect(self._path)
        self._conn.execute("CREATE TABLE inv (id TEXT PRIMARY KEY)")
        self._conn.execute("CREATE TABLE per (id TEXT PRIMARY KEY)")
        self._pending = 0
        self.duplicates = 0

    def add(self, invitation_id: str, person_id: str) -> None:
        cur = self._conn.execute("INSERT OR IGNORE INTO inv (id) VALUES (?)", (invitation_id,))
        if cur.rowcount == 0:
            self.duplicates += 1
        self._conn.execute("INSERT OR IGNORE INTO per (id) VALUES (?)", (person_id,))
        self._pending += 1
        if self._pending >= INDEX_COMMIT_EVERY:
            self._conn.commit()
            self._pending = 0

    def finish(self) -> tuple[int, int]:
        self._conn.commit()
        inv_total = int(self._conn.execute("SELECT COUNT(*) FROM inv").fetchone()[0])
        per_total = int(self._conn.execute("SELECT COUNT(*) FROM per").fetchone()[0])
        self._conn.close()
        return (inv_total, per_total)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.close()


def validate_source(
    explicit: str | None = None,
    member_override: str | None = None,
    use_index: bool = True,
) -> ValidationResult:
    resolved = resolve_source(explicit)
    tmpdir = tempfile.mkdtemp(prefix="rak-screening-")
    index = _DiskIndex(tmpdir) if use_index else None
    rows = 0
    cross = 0
    empties = {"MONTHS_LAST_INVITATION": 0, "MONTHS_SINCE_LAST_SCREEN": 0}
    stream = hashlib.sha256()
    first_hash = ""
    end_hash = ""
    try:
        for lineno, line, raw in iter_raw_lines(resolved, member_override):
            try:
                checked = schema.validate_row(raw)
            except ContractError as exc:
                raise ContractError(
                    code=exc.code, message=f"{exc.message} at row {lineno}"
                ) from exc
            rows += 1
            stream.update(line.encode("utf-8"))
            digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
            if rows == 1:
                first_hash = digest
            end_hash = digest
            cross += schema.cross_mismatch(checked)
            for column in empties:
                if checked[column] == "":
                    empties[column] += 1
            if index is not None:
                index.add(checked["INVITATION_ID"], checked["PERSON_ID"])
        if rows == 0:
            raise ContractError(code="bad_row", message="screening source has no rows")
        mid_hash = ""
        if index is not None:
            inv_total, per_total = index.finish()
            index = None
        else:
            inv_total, per_total = (0, 0)
        mid_index = (rows + 1) // 2
        for current, (_ln, line2, _raw2) in enumerate(
            iter_raw_lines(resolved, member_override), start=1
        ):
            if current == mid_index:
                mid_hash = hashlib.sha256(line2.encode("utf-8")).hexdigest()
                break
    finally:
        if index is not None:
            with contextlib.suppress(Exception):
                index.close()
        shutil.rmtree(tmpdir, ignore_errors=True)
    duplicates = rows - inv_total if use_index else 0
    return ValidationResult(
        rows=rows,
        columns=len(schema.HEADER),
        distinct_persons=per_total,
        duplicate_invitations=duplicates,
        empty_nullable=dict(empties),
        cross_mismatches=cross,
        first_hash=first_hash,
        mid_hash=mid_hash,
        end_hash=end_hash,
        stream_digest=stream.hexdigest(),
        source_bytes=resolved.size_bytes,
    )
