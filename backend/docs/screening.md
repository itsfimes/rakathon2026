# Screening dataset (P3)

The VZP invitation archive is served as a native screening dataset. No FHIR
invention: one CSV row stays one invitation record with all 25 raw strings
preserved. `PERSON_ID` remains personal data; `AGE_BAND` is never a birth date.

Archive identity: `Rakathon2026.zip` member `Rakhaton2026.csv`, 25 columns,
header `INVITATION_ID ... SCREENING_12M_FLAG`. Full-scan evidence (aggregates
only, no record output): 1,344,556 rows, 508,527 distinct persons, 0 duplicate
invitation ids. See `scripts/verify_screening_full.py`.

## Layout

- `b2/screening/schema.py` — exact header, flag/date/int/band checks, raw strings kept
- `b2/screening/reader.py` — trusted local CSV/ZIP streaming, single-row memory
- `b2/screening/ports.py` — `ScreeningPort` query contract
- `b2/screening/archive.py` — read-only MOCK store over the registered source
- `b2/iris/screening_sql.py` — production IRIS adapter (bridge side only)
- `runtime/screening_cmds.py` — `screening-validate/query/import/init-db` handlers
- `scripts/verify_screening_full.py` — opt-in full-dataset proof, never in default pytest

## Validation rules

Strict header and row width. `INVITATION_DATE` is `DD.MM.YYYY`, a real calendar
date, year 2000..2030. Flag columns (`FIRST_INVITATION`, `GP_REGISTERED`,
`GYN_REGISTERED_FLAG`, `NEVER_SCREENED_BEFORE_FLAG`, `SCREENING_3M/6M/12M_FLAG`)
are exactly `A` or `N`. Integer columns accept empty (nullable) or `0..100000`.
Duration bands are empty, `<2`, `2-5`, or `>5`. Registration/band cross
consistency is counted in aggregates, never printed per row. Errors carry row
numbers, never row contents.

Sources register only at trusted startup (`--screening-source` or
`RAKATHON_SCREENING_SOURCE`, optional `RAKATHON_SCREENING_MEMBER`). Plain CSV or
ZIP with the exact member only. Traversal names, missing/duplicate members,
encrypted entries, directory entries, and oversize payloads are rejected. No
source path is ever accepted over IPC.

Memory is O(1): streaming text reader, no pandas, no full read. Duplicate
invitation and distinct person counts use a temporary private disk-backed
SQLite key index (validation only, not backend storage), committed in chunks
and deleted afterwards. Full 182 MB scan peaks at ~31 MB RSS.

## Query contract

`screening.query` takes allowlisted equality filters (12 columns:
`INVITATION_ID`, `PERSON_ID`, `INVITATION_DATE`, `AGE_BAND`,
`VZP_TERRITORIAL_AREA`, plus the 7 flag columns), an allowlisted projection
(any subset of the 25 columns), `limit 1..500`, and `offset 0..2000000`.
Pagination follows stable file order and stops scanning once the page is full,
but unfiltered tail scans still stream. There is no sort index and no latency
promise: deep filtered scans can exceed the 5 s B4→B2 IPC window, so full
validation stays a local CLI operation. Request kind is `metadata`, the
response is `proprietary`. Missing store fails closed with `not_configured`.

Auth: `admin` and `coordinator` allowed; `clinician`, `viewer`, `watchdog`
denied. Unknown users and unassigned pools fail closed.

## Commands

```sh
uv run rakathon-backend screening-validate --source data.zip
uv run rakathon-backend serve --screening-source data.zip
uv run rakathon-backend screening-query --runtime-dir DIR --user admin \
  --filters-json '{"AGE_BAND":"65-69"}' --limit 100
uv run rakathon-backend screening-import --source data.zip --batch-size 500
uv run rakathon-backend screening-init-db
```

`screening-query` prints counts plus a rows digest by default; `--include-rows`
prints records explicitly. `screening-import` streams through the configured
encrypted bridge in idempotent batches and prints counts only.

Existing deployments created with a narrower `INVITATION_ID` column need a
non-destructive migration (widen the column in place, keep every row); never
drop user data and never run ad-hoc DDL outside `screening-init-db` on a fresh
table.

## IRIS adapter

`ScreeningSqlStore` keeps 25 raw `VARCHAR` columns with `INVITATION_ID` as the
primary key. `INVITATION_ID` uses `VARCHAR(64)` so the longest legal value
(`INV` plus 32 digits, 35 characters) is preserved; the width constant is
`INVITATION_ID_WIDTH`. Import is batched (`<= 500`), committed per batch, rolled back on
any failure: new rows insert, identical rows skip, conflicting rows raise
`conflict` instead of silently overwriting. Queries use bound parameters with
an allowlisted projection and filters plus a validated `TOP` cap; IRIS offsets
are additionally capped at 5000. DDL runs only via explicit `screening-init-db`
on the bridge host, never at startup. Bridge operations are `screening.import`
(counts-only reply) and `screening.query`, inside the existing 512 KiB
argument and 1 MiB response envelopes. Live IRIS behavior is NOT verified;
offline fakes prove the SQL shapes, binding, idempotence, and rollback.

## Known limitations

- `B2Service` screening mount is archive-backed MOCK by default, usable offline.
- `fhir.search` is a permission alias of `fhir.read` (canonicalized in B6
  before the unknown-action guard, original action preserved on the wire).
- No resume checkpoint for imports; re-running is idempotent, conflicting
  primary keys abort the batch loudly.
