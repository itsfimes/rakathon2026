from __future__ import annotations

import datetime
import re
from typing import Any

from rakathon_backend.common.errors import ContractError

HEADER: tuple[str, ...] = (
    "INVITATION_ID",
    "PERSON_ID",
    "INVITATION_DATE",
    "AGE_BAND",
    "VZP_TERRITORIAL_AREA",
    "PRIOR_INVITATION_COUNT",
    "MONTHS_LAST_INVITATION",
    "INVITATION_SEQUENCE",
    "HEALTHCARE_CONTACT_12M_CNT",
    "FIRST_INVITATION",
    "INSURANCE_DURATION_YEARS",
    "GP_REGISTERED",
    "GP_REG_DURATION_BAND",
    "GYN_REGISTERED_FLAG",
    "GYN_REG_DURATION_BAND",
    "PRIOR_SCREEN_COUNT_5Y",
    "MONTHS_SINCE_LAST_SCREEN",
    "NEVER_SCREENED_BEFORE_FLAG",
    "GP_PREVENTION_24M_CNT",
    "GYN_PREVENTION_24M_CNT",
    "OTHER_SCREENING_36M_CNT",
    "DENTAL_PREVENTION_24M_CNT",
    "SCREENING_3M_FLAG",
    "SCREENING_6M_FLAG",
    "SCREENING_12M_FLAG",
)

COLUMNS: frozenset[str] = frozenset(HEADER)

FLAG_COLUMNS: frozenset[str] = frozenset(
    {
        "FIRST_INVITATION",
        "GP_REGISTERED",
        "GYN_REGISTERED_FLAG",
        "NEVER_SCREENED_BEFORE_FLAG",
        "SCREENING_3M_FLAG",
        "SCREENING_6M_FLAG",
        "SCREENING_12M_FLAG",
    }
)

FILTERABLE: frozenset[str] = frozenset(
    {
        "INVITATION_ID",
        "PERSON_ID",
        "INVITATION_DATE",
        "AGE_BAND",
        "VZP_TERRITORIAL_AREA",
        "FIRST_INVITATION",
        "GP_REGISTERED",
        "GYN_REGISTERED_FLAG",
        "NEVER_SCREENED_BEFORE_FLAG",
        "SCREENING_3M_FLAG",
        "SCREENING_6M_FLAG",
        "SCREENING_12M_FLAG",
    }
)

INT_COLUMNS: frozenset[str] = frozenset(
    {
        "PRIOR_INVITATION_COUNT",
        "MONTHS_LAST_INVITATION",
        "INVITATION_SEQUENCE",
        "HEALTHCARE_CONTACT_12M_CNT",
        "INSURANCE_DURATION_YEARS",
        "PRIOR_SCREEN_COUNT_5Y",
        "MONTHS_SINCE_LAST_SCREEN",
        "GP_PREVENTION_24M_CNT",
        "GYN_PREVENTION_24M_CNT",
        "OTHER_SCREENING_36M_CNT",
        "DENTAL_PREVENTION_24M_CNT",
    }
)

DURATION_BANDS: frozenset[str] = frozenset({"", "<2", "2-5", ">5"})

MAX_FIELD_CHARS = 64
MAX_REGION_CHARS = 64
MAX_INT_VALUE = 100000
MIN_DATE_YEAR = 2000
MAX_DATE_YEAR = 2030

_INV_RE = re.compile(r"^INV[0-9]{1,32}$")
_PERSON_RE = re.compile(r"^[0-9]{1,32}$")
_AGE_RE = re.compile(r"^([0-9]{2}-[0-9]{2}|85\+)$")
_DATE_RE = re.compile(r"^[0-9]{2}\.[0-9]{2}\.[0-9]{4}$")


def check_header(names: list[str] | tuple[str, ...]) -> None:
    given = list(names)
    if given != list(HEADER):
        raise ContractError(
            code="bad_header",
            message=f"screening header mismatch: got {len(given)} columns, want {len(HEADER)}",
        )


def _check_id(column: str, value: str) -> None:
    if len(value) > MAX_FIELD_CHARS:
        raise ContractError(code="bad_row", message=f"column {column} exceeds length cap")
    if column == "INVITATION_ID":
        if _INV_RE.fullmatch(value) is None:
            raise ContractError(code="bad_row", message="column INVITATION_ID has bad shape")
    elif _PERSON_RE.fullmatch(value) is None:
        raise ContractError(code="bad_row", message="column PERSON_ID has bad shape")


def _check_date(value: str) -> None:
    if _DATE_RE.fullmatch(value) is None:
        raise ContractError(code="bad_row", message="column INVITATION_DATE has bad shape")
    try:
        parsed = datetime.datetime.strptime(value, "%d.%m.%Y")
    except ValueError as exc:
        raise ContractError(code="bad_row", message="column INVITATION_DATE is not a date") from exc
    if not (MIN_DATE_YEAR <= parsed.year <= MAX_DATE_YEAR):
        raise ContractError(code="bad_row", message="column INVITATION_DATE year out of range")


def _check_int(column: str, value: str) -> None:
    if value == "":
        return
    if len(value) > 16:
        raise ContractError(code="bad_row", message=f"column {column} exceeds length cap")
    try:
        number = int(value)
    except ValueError as exc:
        raise ContractError(code="bad_row", message=f"column {column} is not an integer") from exc
    if number < 0 or number > MAX_INT_VALUE:
        raise ContractError(code="bad_row", message=f"column {column} out of range")


def _check_text(column: str, value: str, cap: int) -> None:
    if not value or len(value) > cap:
        raise ContractError(code="bad_row", message=f"column {column} has bad text")


def validate_row(row: dict[str, Any]) -> dict[str, str]:
    if set(row) != set(HEADER):
        raise ContractError(code="bad_row", message="row width mismatch")
    out: dict[str, str] = {}
    for column in HEADER:
        value = row.get(column)
        if not isinstance(value, str):
            raise ContractError(code="bad_row", message=f"column {column} is not a string")
        out[column] = value
    _check_id("INVITATION_ID", out["INVITATION_ID"])
    _check_id("PERSON_ID", out["PERSON_ID"])
    if not out["INVITATION_ID"] or not out["PERSON_ID"]:
        raise ContractError(code="bad_row", message="id columns must be nonempty")
    _check_date(out["INVITATION_DATE"])
    if _AGE_RE.fullmatch(out["AGE_BAND"]) is None:
        raise ContractError(code="bad_row", message="column AGE_BAND has bad shape")
    _check_text("VZP_TERRITORIAL_AREA", out["VZP_TERRITORIAL_AREA"], MAX_REGION_CHARS)
    for column in FLAG_COLUMNS:
        if out[column] not in ("A", "N"):
            raise ContractError(code="bad_row", message=f"column {column} must be A or N")
    for column in INT_COLUMNS:
        _check_int(column, out[column])
    for column in ("GP_REG_DURATION_BAND", "GYN_REG_DURATION_BAND"):
        if out[column] not in DURATION_BANDS:
            raise ContractError(code="bad_row", message=f"column {column} has bad band")
    return out


def cross_mismatch(row: dict[str, str]) -> int:
    bad = 0
    if (row["GP_REGISTERED"] == "N") != (row["GP_REG_DURATION_BAND"] == ""):
        bad += 1
    if (row["GYN_REGISTERED_FLAG"] == "N") != (row["GYN_REG_DURATION_BAND"] == ""):
        bad += 1
    return bad
