import hashlib
import os

OUT = "/tmp/opencode/converter-fixtures"


def esc(s: str) -> str:
    s = s.replace("\\", "\\\\")
    s = s.replace("(", "\\(")
    s = s.replace(")", "\\)")
    out = ""
    for ch in s:
        o = ord(ch)
        if 32 <= o <= 126:
            out += ch
        else:
            out += "?"
    return out


def page_stream(lines: list[str], title_size: int = 13, body_size: int = 10) -> str:
    parts = []
    y = 740
    parts.append(f"BT /F1 {title_size} Tf 72 {y} Td ({esc(lines[0])}) Tj ET")
    y -= 22
    for ln in lines[1:]:
        parts.append(f"BT /F1 {body_size} Tf 72 {y} Td ({esc(ln)}) Tj ET")
        y -= 14
        if y < 60:
            break
    return "\n".join(parts) + "\n"


def write_pdf(path: str, pages: list[list[str]]) -> None:
    objs = {}
    n = len(pages)
    page_ids = [4 + i * 2 for i in range(n)]
    content_ids = [5 + i * 2 for i in range(n)]
    info_id = 4 + n * 2
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{p} 0 R" for p in page_ids)
    objs[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode("ascii")
    objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for pid, cid, lines in zip(page_ids, content_ids, pages):
        stream = page_stream(lines).encode("ascii")
        objs[cid] = (
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream"
        )
        objs[pid] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {cid} 0 R >>"
        ).encode("ascii")
    objs[info_id] = (
        b"<< /Title (SYNTHETIC TEST ONLY) /Producer (converter-fixture-gen stdlib) /CreationDate (D:20260101000000Z) >>"
    )
    size = info_id + 1
    data = bytearray()
    data += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = {}
    for oid in range(1, size):
        offsets[oid] = len(data)
        data += f"{oid} 0 obj\n".encode("ascii")
        data += objs[oid]
        data += b"\nendobj\n"
    xref_pos = len(data)
    data += f"xref\n0 {size}\n".encode("ascii")
    data += b"0000000000 65535 f \n"
    for oid in range(1, size):
        data += f"{offsets[oid]:010d} 00000 n \n".encode("ascii")
    data += (
        f"trailer\n<< /Size {size} /Root 1 0 R /Info {info_id} 0 R "
        f"/ID [<AAAAAAAAAAAAAAAA> <BBBBBBBBBBBBBBBB>] >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode("ascii")
    with open(path, "wb") as f:
        f.write(bytes(data))


def fixture_lab() -> list[list[str]]:
    return [
        [
            "SYNTHETIC TEST ONLY - NOT REAL PATIENT DATA",
            "NOVA-CARE HOSPITAL - CODED LAB REPORT - FORM LC-7 REV 4",
            "FAC: NCH-SYNTH-07 | DEPT: LAB | PANEL: METAB-7S",
            "PAT: ZEBRA, ZELDA TEST-001 | MRN: SYN-000001 | DOB: 2000-01-31",
            "VISIT: LV-2026-0001 | COLLECTED: 2026-02-02 08:10 UTC | RPT: 2026-02-02 10:00 UTC",
            "",
            "CODED RESULTS (CODE | VALUE | UNIT | REF | FLAG):",
            "TST^GLU-F: 102 | mg/dL | 70-99 | H",
            "TST^NA-S: 140 | mmol/L | 136-145 | N",
            "TST^K-S: 4.1 | mmol/L | 3.5-5.1 | N",
            "TST^CRE-S: 0.9 | mg/dL | 0.6-1.1 | N",
            "TST^HGB-B: 13.5 | g/dL | 12.0-16.0 | N",
            "",
            "OPERATOR: SYN-OP-12 | VERIFIED: YES | PAGE 1 OF 1",
            "NOTE: SYNTHETIC VALUES FOR CONVERTER TESTING ONLY.",
        ]
    ]


def fixture_discharge() -> list[list[str]]:
    p1 = [
        "SYNTHETIC TEST ONLY - NOT REAL PATIENT DATA",
        "HARBOURVIEW HOSPITAL - DISCHARGE SUMMARY DS-2",
        "PAT: YARROW, YUSUF TEST-002 | MRN: SYN-000002 | DOB: 1990-06-15",
        "ADMIT: 2026-03-01 | DISCHARGE: 2026-03-04 | WARD: 3B-SYNTH",
        "ATTENDING: DR. INVENTED IBIS-9 | VISIT: HV-2026-0002",
        "",
        "CHIEF COMPLAINT: Synthetic test cough for 3 days.",
        "HISTORY: Invented scenario. No real encounter occurred.",
        "COURSE: Routine synthetic observation. Vitals stable.",
        "MEDS AT DISCHARGE:",
        "- Drugaphen 250 mg by mouth twice daily for 5 days",
        "- Placebosol 10 mL at bedtime as needed",
        "FOLLOWUP: Synthetic clinic in 7 days. PAGE 1 OF 2.",
    ]
    p2 = [
        "SYNTHETIC TEST ONLY - NOT REAL PATIENT DATA",
        "HARBOURVIEW DS-2 CONTINUED - PAGE 2 OF 2",
        "PAT: YARROW, YUSUF TEST-002 | MRN: SYN-000002",
        "DIAGNOSES: J06.9 Synthetic upper airway test case",
        "PROCEDURES: None. Labs: synthetic panel only.",
        "INSTRUCTIONS: Rest, fluids, return if worsens.",
        "CONTACT: Synthetic line 555-0100. No real PHI.",
        "SIGN: DR. INVENTED IBIS-9 | 2026-03-04 12:00 UTC",
    ]
    return [p1, p2]


def fixture_tricky() -> list[list[str]]:
    p1 = [
        "SYNTHETIC TEST ONLY - NOT REAL PATIENT DATA",
        "MERIDIAN TEST CLINIC - MIXED PANEL MX-9 (TRICKY)",
        "PAT: QUINN, QUINCY TEST-003A | MRN: SYN-000003 | DOB: 1985-12-12",
        "VISIT: MX-2026-0003 | COLLECTED: 03/04/05 (AMBIGUOUS, DO NOT NORMALIZE)",
        "",
        "RESULTS WITH MISSING UNITS:",
        "TST^GLU-F: 98 | UNIT MISSING | REF 70-99 | FLAG N",
        "TST^K-S: 4.0? (ILLEGIBLE QUERY MARK, VERIFY MANUALLY)",
        "TST^WBC-B: 6.2 | UNIT MISSING | REF 4.5-11.0 | FLAG N",
        "",
        "NOTE: DATE FORMAT INTENTIONALLY AMBIGUOUS. PAGE 1 OF 2.",
    ]
    p2 = [
        "SYNTHETIC TEST ONLY - NOT REAL PATIENT DATA",
        "MERIDIAN MX-9 CONTINUED - PAGE 2 OF 2 - CONFLICT CASE",
        "HEADER REPRINTS DIFFERENT ID: MRN: SYN-000099 (CONFLICTS WITH PAGE 1)",
        "PAT REPRINT: QUINN, QUINCY TEST-003A | VISIT: MX-2026-0003",
        "TST^NA-S: 139 | mmol/L | 136-145 | N",
        "TST^CRE-S: PENDING - NO VALUE REPORTED",
        "RULE: CONVERTER MUST FLAG ID CONFLICT, MUST NOT GUESS.",
        "OPERATOR: SYN-OP-77 | PAGE 2 OF 2.",
    ]
    return [p1, p2]


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    jobs = [
        ("fixture_01_lab_report.pdf", fixture_lab()),
        ("fixture_02_discharge_narrative.pdf", fixture_discharge()),
        ("fixture_03_ambiguity_conflict.pdf", fixture_tricky()),
    ]
    for name, pages in jobs:
        write_pdf(os.path.join(OUT, name), pages)
    sums = []
    for name, _ in jobs:
        p = os.path.join(OUT, name)
        with open(p, "rb") as handle:
            h = hashlib.sha256(handle.read()).hexdigest()
        sums.append(f"{h}  {name}")
    with open(os.path.join(OUT, "SHA256SUMS.txt"), "w") as handle:
        handle.write("\n".join(sums) + "\n")
    print("\n".join(sums))


if __name__ == "__main__":
    main()
