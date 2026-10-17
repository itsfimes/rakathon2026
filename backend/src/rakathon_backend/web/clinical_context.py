from __future__ import annotations

from typing import Any

from rakathon_backend.web.clinical_codes import REPORTS, RESULT_STATUS
from rakathon_backend.web.clinical_facts import (
    Fact, condition_fact, loinc, newest, observation_facts, ordered, source_time,
)
from rakathon_backend.web.projection import belongs_to

FIELD_SOURCES = {
    "record.coverage": "record-coverage",
    "record.timeQualification": "record-context-limits",
    "record.selection": "record-context-limits",
    "record.conditions": "record-clinical-conditions",
    "record.measurements": "record-clinical-measurements",
    "record.reportsSummary": "record-report-metadata",
}
COMMON_FIELDS = frozenset(("record.coverage", "record.timeQualification", "record.selection"))


def field(key: str, value: str) -> dict[str, str]:
    return {"key": key, "source": FIELD_SOURCES[key], "value": value}


def report_facts(case: dict[str, Any], observations: dict[str, list[Fact]]) -> tuple[list[Fact], int]:
    result = []
    unsupported = 0
    for report in case["sections"]["diagnosticReports"]["items"]:
        code = loinc(report.get("code"), REPORTS)
        if code is None or not belongs_to(report, case["patient"]["id"]):
            unsupported += 1
            continue
        occurred, year = source_time(report)
        label = REPORTS[code]
        status = RESULT_STATUS.get(report.get("status", ""), "neuveden")
        prefix = f"{label}; stav: {status}; {year}"
        references = {ref.get("reference") for ref in report.get("result", []) if isinstance(ref, dict) and isinstance(ref.get("reference"), str)}
        linked = newest([fact for ref in sorted(references) for fact in observations.get(ref, [])])
        selected: list[str] = []
        for fact in linked[:2]:
            if len(prefix + "; výběr výsledků: " + "; ".join([*selected, fact.short]) + "; nepředané odkazy: 500") <= 320:
                selected.append(fact.short)
        missing = sum(ref not in observations for ref in references)
        value = prefix + ("; výběr výsledků: " + "; ".join(selected) if selected else "; ověřené výsledky nepředány")
        value += f"; výběr faktů {len(selected)}/{len(linked)}; nedostupné odkazy {missing}"
        if len(value) > 320:
            value = f"{prefix}; výsledky nepředány kvůli rozpočtu; nedostupné odkazy {missing}"
        result.append(Fact(code, list(REPORTS).index(code), value, label, occurred, str(report.get("id", ""))))
    return result, unsupported


def context_for(case: dict[str, Any], role: str) -> dict[str, Any]:
    sections = case["sections"]
    labels = {"conditions": "Onemocnění", "observations": "Pozorování", "diagnosticReports": "Zprávy", "documents": "Dokumenty"}
    coverage = "; ".join(f"{label}: {'načteno' if sections[key]['status'] == 'complete' else 'nedostupné'}" for key, label in labels.items())
    fields = [field("record.coverage", coverage), field("record.timeQualification", "Citlivý odidentifikovaný výběr, ne zaručená anonymita. Zdrojový rok není současný stav; současný stav neznámý. Chybějící rozmezí neznamená normální výsledek. Dotaz se automaticky neanonymizuje.")]
    if role == "koordinator":
        fields.append(field("record.selection", "Klinické údaje se pro tuto roli nepředávají. Pracovní postup zdroj neposkytl. Nejde o celý zdravotní záznam."))
        return {"role": role, "fields": fields}
    patient_id = case["patient"]["id"]
    conditions: list[Fact] = []
    measurements: list[Fact] = []
    observations: dict[str, list[Fact]] = {}
    unsupported = len(sections["documents"]["items"])
    for item in sections["conditions"]["items"]:
        fact = condition_fact(item, patient_id)
        if fact is None:
            unsupported += 1
        else:
            conditions.append(fact)
    for item in sections["observations"]["items"]:
        facts, skipped = observation_facts(item, patient_id)
        measurements.extend(facts)
        observations["Observation/" + item["id"]] = facts
        unsupported += skipped
    reports, skipped = report_facts(case, observations)
    unsupported += skipped
    limits = (3, 6, 2) if role == "pacient" else (5, 10, 3)
    candidates = (("record.conditions", conditions), ("record.measurements", measurements), ("record.reportsSummary", reports))
    selected_counts = []
    omitted = 0
    # The final honesty field reserves its full320-character budget before facts.
    available = 4000 - sum(len(item["value"]) for item in fields) - 320
    selected_fields = []
    for (key, facts), maximum in zip(candidates, limits, strict=True):
        selected = 0
        for fact in newest(facts)[:maximum]:
            if len(fact.value) <= min(320, available):
                selected_fields.append(field(key, fact.value))
                available -= len(fact.value)
                selected += 1
        selected_counts.append(selected)
        omitted += len(facts) - selected
    unavailable = sum(section["status"] != "complete" for section in sections.values())
    absent = sum(section["status"] == "complete" and not section["items"] for section in sections.values())
    selection = f"Výběr: onemocnění {selected_counts[0]}, fakta měření {selected_counts[1]}, zprávy {selected_counts[2]}. Nepředáno podporovaných položek {omitted}; nepodporovaných {unsupported}; nedostupných částí {unavailable}; načtených prázdných částí {absent}. Nejde o celý záznam; počty jsou výběrové položky, ne počet pacientových diagnóz."
    fields.extend([field("record.selection", selection), *selected_fields])
    return {"role": role, "fields": fields}
