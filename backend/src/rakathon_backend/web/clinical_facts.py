from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from rakathon_backend.web.clinical_codes import (
    CLINICAL_STATUS, CONDITIONS, LOINC, MEASUREMENTS, RESULT_STATUS, UCUM, VERIFICATION,
)
from rakathon_backend.web.projection import belongs_to


@dataclass(frozen=True)
class Fact:
    key: str
    priority: int
    value: str
    short: str
    occurred: float
    identity: str


def coding_keys(concept: Any) -> set[tuple[str, str]]:
    if not isinstance(concept, dict) or not isinstance(concept.get("coding", []), list):
        return set()
    return {
        (item["system"], item["code"])
        for item in concept.get("coding", [])
        if isinstance(item, dict) and isinstance(item.get("system"), str)
        and isinstance(item.get("code"), str)
    }


def recognized(concept: Any, allowed: dict[tuple[str, str], Any]) -> tuple[str, str] | None:
    keys = coding_keys(concept) & allowed.keys()
    return next(iter(keys)) if len(keys) == 1 else None


def loinc(concept: Any, allowed: dict[str, Any]) -> str | None:
    key = recognized(concept, {(LOINC, code): None for code in allowed})
    return key[1] if key else None


def source_time(resource: dict[str, Any]) -> tuple[float, str]:
    raw = next((resource[key] for key in ("effectiveDateTime", "onsetDateTime", "issued", "recordedDate") if resource.get(key)), None)
    if raw is None:
        raw = resource.get("effectivePeriod", {}).get("start")
    if isinstance(raw, str) and re.fullmatch(r"[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2}(?:T.+)?)?)?", raw):
        try:
            parsed = datetime.fromisoformat(raw if len(raw) > 7 else raw + ("-01-01" if len(raw) == 4 else "-01"))
            parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
            return parsed.timestamp(), f"zdrojový rok {parsed.year}"
        except (ValueError, OverflowError):
            pass
    return float("-inf"), "zdrojový rok neznámý"


def source_status(concept: Any, suffix: str, allowed: dict[str, str]) -> str:
    keys = {code for system, code in coding_keys(concept) if system == "http://terminology.hl7.org/CodeSystem/" + suffix}
    return allowed.get(next(iter(keys)), "neuvedeno") if len(keys) == 1 else "neuvedeno"


def condition_fact(resource: dict[str, Any], patient_id: str) -> Fact | None:
    key = recognized(resource.get("code"), CONDITIONS)
    if key is None or not belongs_to(resource, patient_id):
        return None
    clinical = source_status(resource.get("clinicalStatus"), "condition-clinical", CLINICAL_STATUS)
    verification = source_status(resource.get("verificationStatus"), "condition-ver-status", VERIFICATION)
    occurred, year = source_time(resource)
    label = CONDITIONS[key]
    value = f"{label}; stav: {clinical}; ověření: {verification}; {year}"
    return Fact("|".join(key), list(CONDITIONS).index(key), value, label, occurred, str(resource.get("id", "")))


def quantity(value: Any, aliases: dict[str, str]) -> tuple[str, str] | None:
    if not isinstance(value, dict) or value.get("system") != UCUM:
        return None
    number = value.get("value")
    try:
        if type(number) not in (int, float) or not math.isfinite(number):
            return None
    except OverflowError:
        return None
    code, unit = value.get("code"), value.get("unit")
    if not isinstance(code, str) or code not in aliases:
        return None
    if unit is not None and (not isinstance(unit, str) or aliases.get(unit) != aliases[code]):
        return None
    literal = str(number)
    return (literal, aliases[code]) if len(literal) <= 32 else None


def observation_facts(resource: dict[str, Any], patient_id: str) -> tuple[list[Fact], int]:
    if not belongs_to(resource, patient_id):
        return [], 1
    occurred, year = source_time(resource)
    identity = str(resource.get("id", ""))
    status = RESULT_STATUS.get(resource.get("status", ""), "neuveden")
    components = resource.get("component", [])
    facts: list[Fact] = []
    unsupported = 0
    bp = loinc(resource.get("code"), {"85354-9": None}) is not None
    if bp:
        pressures = {}
        for component in components:
            code = loinc(component.get("code"), {"8480-6": None, "8462-4": None})
            if code:
                pressures.setdefault(code, []).append(quantity(component.get("valueQuantity"), MEASUREMENTS[code][1]))
        if all(len(pressures.get(code, [])) == 1 and pressures[code][0] is not None for code in ("8480-6", "8462-4")):
            systolic, diastolic = pressures["8480-6"][0], pressures["8462-4"][0]
            short = f"Krevní tlak: {systolic[0]}/{diastolic[0]} mmHg"
            facts.append(Fact("BP", -1, f"{short}; {year}; stav výsledku: {status}", short, occurred, identity))
    items = ([] if components and "valueQuantity" not in resource else [resource]) + components
    for index, item in enumerate(items):
        code = loinc(item.get("code"), MEASUREMENTS)
        if bp and facts and code in ("8480-6", "8462-4"):
            continue
        measured = quantity(item.get("valueQuantity"), MEASUREMENTS[code][1]) if code else None
        if code is None or measured is None:
            unsupported += 1
            continue
        short = f"{MEASUREMENTS[code][0]}: {measured[0]} {measured[1]}"
        facts.append(Fact(code, list(MEASUREMENTS).index(code), f"{short}; {year}; stav výsledku: {status}", short, occurred, f"{identity}/{index}"))
    return facts, unsupported


def ordered(facts: list[Fact]) -> list[Fact]:
    return sorted(facts, key=lambda fact: (fact.priority, -fact.occurred, fact.identity))


def newest(facts: list[Fact]) -> list[Fact]:
    result: dict[str, Fact] = {}
    for fact in ordered(facts):
        result.setdefault(fact.key, fact)
    return list(result.values())
