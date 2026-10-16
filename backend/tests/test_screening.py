from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Any

import pytest

from rakathon_backend.b2.screening import archive, schema
from rakathon_backend.b2.screening.archive import ArchiveScreeningStore
from rakathon_backend.b2.screening.reader import (
    ResolvedSource,
    iter_validated_rows,
    resolve_source,
    validate_source,
)
from rakathon_backend.b6.permissions import canonical_action, check, load_matrix
from rakathon_backend.common.errors import ContractError


def _row(inv: str, person: str, **over: str) -> dict[str, str]:
    base: dict[str, str] = {
        "INVITATION_ID": inv,
        "PERSON_ID": person,
        "INVITATION_DATE": "14.01.2020",
        "AGE_BAND": "65-69",
        "VZP_TERRITORIAL_AREA": "PRAHA",
        "PRIOR_INVITATION_COUNT": "1",
        "MONTHS_LAST_INVITATION": "12",
        "INVITATION_SEQUENCE": "2",
        "HEALTHCARE_CONTACT_12M_CNT": "3",
        "FIRST_INVITATION": "N",
        "INSURANCE_DURATION_YEARS": "10",
        "GP_REGISTERED": "A",
        "GP_REG_DURATION_BAND": ">5",
        "GYN_REGISTERED_FLAG": "N",
        "GYN_REG_DURATION_BAND": "",
        "PRIOR_SCREEN_COUNT_5Y": "0",
        "MONTHS_SINCE_LAST_SCREEN": "",
        "NEVER_SCREENED_BEFORE_FLAG": "A",
        "GP_PREVENTION_24M_CNT": "1",
        "GYN_PREVENTION_24M_CNT": "0",
        "OTHER_SCREENING_36M_CNT": "0",
        "DENTAL_PREVENTION_24M_CNT": "2",
        "SCREENING_3M_FLAG": "N",
        "SCREENING_6M_FLAG": "N",
        "SCREENING_12M_FLAG": "N",
    }
    base.update(over)
    return base


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(schema.HEADER))
        writer.writeheader()
        writer.writerows(rows)


def _write_zip(path: Path, inner: str, rows: list[dict[str, str]]) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(schema.HEADER))
    writer.writeheader()
    writer.writerows(rows)
    with zipfile.ZipFile(str(path), "w", compression=zipfile.ZIP_DEFLATED) as archive_file:
        archive_file.writestr(inner, buf.getvalue())


def _resolved_csv(tmp_path: Path, rows: list[dict[str, str]]) -> ResolvedSource:
    target = tmp_path / "sample.csv"
    _write_csv(target, rows)
    return resolve_source(str(target))


def test_header_exact() -> None:
    assert len(schema.HEADER) == 25
    with pytest.raises(ContractError):
        schema.check_header(["INVITATION_ID"])
    schema.check_header(list(schema.HEADER))


def test_row_ok_and_raw_preserved() -> None:
    row = _row("INV1", "123")
    checked = schema.validate_row(dict(row))
    assert checked == row


def test_row_rejects_bad_date_flag_int_width() -> None:
    bad_date = _row("INV1", "123")
    bad_date["INVITATION_DATE"] = "2020-01-14"
    with pytest.raises(ContractError):
        schema.validate_row(bad_date)
    bad_flag = _row("INV1", "123")
    bad_flag["GP_REGISTERED"] = "Y"
    with pytest.raises(ContractError):
        schema.validate_row(bad_flag)
    bad_int = _row("INV1", "123")
    bad_int["PRIOR_INVITATION_COUNT"] = "abc"
    with pytest.raises(ContractError):
        schema.validate_row(bad_int)
    bad_id = _row("XXX", "123")
    with pytest.raises(ContractError):
        schema.validate_row(bad_id)
    short = {"INVITATION_ID": "INV1"}
    with pytest.raises(ContractError):
        schema.validate_row(short)


def test_nullable_ints_accepted() -> None:
    row = _row("INV1", "123", MONTHS_LAST_INVITATION="", MONTHS_SINCE_LAST_SCREEN="")
    assert schema.validate_row(row)["MONTHS_LAST_INVITATION"] == ""


def test_validate_counts_duplicates_and_hashes(tmp_path: Path, monkeypatch: Any) -> None:
    rows = [
        _row("INV1", "111"),
        _row("INV2", "111"),
        _row("INV2", "222"),
        _row("INV3", "333"),
    ]
    target = tmp_path / "sample.csv"
    _write_csv(target, rows)
    monkeypatch.delenv("RAKATHON_SCREENING_SOURCE", raising=False)
    result = validate_source(explicit=str(target))
    assert result.rows == 4
    assert result.columns == 25
    assert result.distinct_persons == 3
    assert result.duplicate_invitations == 1
    assert result.first_hash and result.mid_hash and result.end_hash
    assert result.first_hash != result.end_hash
    again = validate_source(explicit=str(target))
    assert again.stream_digest == result.stream_digest
    assert again.first_hash == result.first_hash


def test_zip_exact_member_and_rejections(tmp_path: Path) -> None:
    rows = [_row("INV1", "111")]
    zpath = tmp_path / "pack.zip"
    _write_zip(zpath, "inner.csv", rows)
    resolved = resolve_source(str(zpath))
    assert resolved.is_zip is True
    with pytest.raises(ContractError):
        list(iter_validated_rows(resolved, "../evil.csv"))
    with pytest.raises(ContractError):
        list(iter_validated_rows(resolved, "missing.csv"))
    plain = tmp_path / "plain.csv"
    _write_csv(plain, rows)
    resolved_plain = resolve_source(str(plain))
    with pytest.raises(ContractError):
        list(iter_validated_rows(resolved_plain, "inner.csv"))


def test_query_filters_projection_bounds(tmp_path: Path) -> None:
    rows = [_row(f"INV{i}", f"90{i}", AGE_BAND="70-74" if i > 1 else "65-69") for i in range(5)]
    store = ArchiveScreeningStore(_resolved_csv(tmp_path, rows))
    page = store.query({"AGE_BAND": "70-74"}, ["INVITATION_ID"], 10, 0)
    assert len(page.rows) == 3
    assert set(page.rows[0]) == {"INVITATION_ID"}
    assert page.truncated is False
    page2 = store.query({}, None, 2, 0)
    assert len(page2.rows) == 2 and page2.truncated is True
    with pytest.raises(ContractError):
        store.query({}, None, 0, 0)
    with pytest.raises(ContractError):
        store.query({}, None, 501, 0)
    with pytest.raises(ContractError):
        store.query({}, None, 10, -1)
    with pytest.raises(ContractError):
        store.query({"nope": "x"}, None, 10, 0)
    with pytest.raises(ContractError):
        store.query({}, ["PERSON_ID", "PERSON_ID"], 10, 0)
    with pytest.raises(ContractError):
        store.query({}, ["UNKNOWN_COL"], 10, 0)


def test_query_exact_lookup_and_offset(tmp_path: Path) -> None:
    rows = [_row(f"INV{i}", f"70{i}") for i in range(3)]
    store = ArchiveScreeningStore(_resolved_csv(tmp_path, rows))
    found = store.query({"INVITATION_ID": "INV1"}, None, 10, 0)
    assert len(found.rows) == 1 and found.rows[0]["PERSON_ID"] == "701"
    shifted = store.query({}, ["INVITATION_ID"], 10, 2)
    assert [r["INVITATION_ID"] for r in shifted.rows] == ["INV2"]


def test_b6_canonical_search_and_screening_matrix() -> None:
    assert canonical_action("fhir.search") == "fhir.read"
    assert canonical_action("fhir.read") == "fhir.read"
    policy = load_matrix()
    assert check(policy, "admin", "fhir.search").allowed is True
    assert check(policy, "viewer", "fhir.search").allowed is True
    assert check(policy, "viewer", "fhir.write").allowed is False
    assert check(policy, "viewer", "nope").allowed is False
    assert check(policy, "admin", "screening.query").allowed is True
    assert check(policy, "coordinator", "screening.query").allowed is True
    assert check(policy, "clinician", "screening.query").allowed is False
    assert check(policy, "viewer", "screening.query").allowed is False
    assert check(policy, "watchdog", "screening.query").allowed is False


def test_query_args_reject_injection() -> None:
    with pytest.raises(ContractError):
        archive.check_query_args({"INVITATION_ID; DROP": "x"}, None, 10, 0)
    with pytest.raises(ContractError):
        archive.check_query_args({"PERSON_ID": "x" * 300}, None, 10, 0)
