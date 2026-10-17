# Rakathon 2026 backend — offline demo (S1) + opt-in local AI (S3) + DOCX ingest (P2)

Runnable offline Python demo over authenticated Unix sockets. No frontend, no
network, no IRIS yet. Default AI path is a labelled mock; a direct HTTP
adapter exists but stays disabled unless explicitly opted in. P2 adds stdlib
DOCX extraction in B1 plus an `ingest-file` CLI that converts a local file
inside a private ephemeral runtime.

## Layout

- `src/rakathon_backend/common/` — `contracts`, `errors`, `config`, `ipc`,
  `framing`, `health`, `rpc`, `blob_store`, `fhir` (shared FHIR allowlist)
- `src/rakathon_backend/b1/` — `docx` (secure OOXML extract), translation
  plus ingest service (mock via B5, DOCX via derived-text ref only)
- `src/rakathon_backend/b2/` — storage protocol, mock memory, thin service
- `src/rakathon_backend/b3/` — watchdog computation plus tick service
- `src/rakathon_backend/b4/` — frontend router with B6 checks
- `src/rakathon_backend/b5/` — AI gateway with mock adapter and kill switch
- `src/rakathon_backend/b5/direct.py`, `direct_http.py` — opt-in direct HTTP
  adapter and transport for Azure/OpenAI-compatible providers
- `src/rakathon_backend/runtime/` — single-process servers, fixtures, demo,
  `application` (BackendApp), `commands` (CLI command helpers), `ingest`
  (`ingest-file` conversion inside an owned ephemeral runtime)
- `src/rakathon_backend/cli.py` — `demo`, `serve`, `client`, `health`,
  `ingest-file`, plus bridge commands
- `docs/contracts.md` — physical/logical connector contract
- `docs/direct-ingestion.md` — direct AI configuration and ingestion contract

## Run

```sh
uv sync --python 3.13
uv run rakathon-backend demo
uv run pytest -W error
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
python -m compileall -q src
```

Serve and mock client:

```sh
uv run rakathon-backend serve --runtime-dir /tmp/opencode/rak-demo
uv run rakathon-backend health --runtime-dir /tmp/opencode/rak-demo
uv run rakathon-backend client --runtime-dir /tmp/opencode/rak-demo \
  --user clinician --action reminders.read --payload-json '{}'
```

The serve command writes `demo-client.json` with mode 0600 inside the runtime
directory only. Client config is a mock identity and never leaves that dir.

## AI modes

```sh
uv run rakathon-backend serve --ai mock
RAKATHON_AI_ENABLE=1 AI_DISABLED=0 RAKATHON_AI_ALLOW_LOOPBACK=1 \
RAKATHON_AI_PROVIDER_KIND=openai-compatible RAKATHON_AI_AUTH_SCHEME=none \
RAKATHON_AI_MODEL=example-model RAKATHON_AI_BASE_URL=http://127.0.0.1:11434/v1 \
  uv run rakathon-backend serve --ai direct --watchdog-interval 1.0
```

`demo` always uses the mock adapter and is unchanged. `serve --ai direct`
refuses to start without explicit provider configuration and opt-in, and never
falls back to mock on failure. Storage and AI modes (`mock`/`direct`) are
reported separately. See `docs/direct-ingestion.md`.

Azure configuration (`RAKATHON_AI_PROVIDER_KIND=azure`, explicit remote consent):

```sh
export RAKATHON_AI_ENABLE=1
export AI_DISABLED=0
export RAKATHON_AI_ALLOW_REMOTE=1
export RAKATHON_AI_PROVIDER_KIND=azure
export RAKATHON_AI_AUTH_SCHEME=api-key
export RAKATHON_AI_MODEL=gpt-6-luna-dz-eu
export RAKATHON_AI_BASE_URL=https://apim-rakathon-q7146n.azure-api.net/openai/v1
uv run rakathon-backend serve --ai direct --env-file .env --watchdog-interval 1.0
```

`.env` (mode 0600, owner-only) holds only `RAKATHON_AI_API_KEY`; it is
never auto-loaded and the key alone never enables AI. `azure-env.example` and
`direct-env.example` document the direct configuration schema without secrets.

## Example demo output

```json
{
  "mode": "mock",
  "synthetic": true,
  "completeIngest": {"resourceType": "Bundle", "patientId": "pat-demo-001"},
  "incompleteIngest": {"resourceType": "OperationOutcome", "manualReview": true},
  "watchdogTickCount": 1,
  "reminderCount": 1,
  "fhirReadTotal": 1,
  "ackStatus": "ACKED",
  "viewerWriteDenied": true,
  "health": {
    "b1": "HEALTHY", "b2": "HEALTHY", "b3": "HEALTHY",
    "b4": "HEALTHY", "b5": "HEALTHY", "b6": "HEALTHY"
  }
}
```

No tokens are printed. All fixtures are synthetic.

## DOCX ingest (P2)

B1 extracts `.docx` locally with stdlib `zipfile` + `ElementTree` only: no
`extractall`, no network, no macro/embedded/external content. Bounds:
256 KiB compressed input, 128 entries, 512 KiB per entry, 1 MiB expanded
total, 64 KiB extracted text. Encryption, `DOCTYPE`/`ENTITY` (including a
UTF-16 null-masked bypass probe), external relationships, traversal,
absolute or duplicate names, and oversize payloads are rejected with typed
errors that never echo document bytes. Paragraphs and tables are read in
document order with cell/row boundaries kept and heading text prefixed `#`.

The original DOCX blob stays in the private ephemeral B1 store; B1 sends
only a derived bounded `text/plain` blob ref to B5, then deletes the derived
copy. Provenance is server-attached, never model-invented: the reply bundle
carries `meta.source = urn:sha256:<original>` plus `sourceHash`/`sourceUrn`
aggregates. Original blob lifetime is the ephemeral runtime lifetime and the
runtime directory is removed on exit.

Shared structural FHIR allowlist lives in `common/fhir.py` and is consumed
by B1, B2 memory/IRIS, and bridge validators so the sets cannot drift:
`Patient`, `ServiceRequest`, `Observation`, `DiagnosticReport`,
`DocumentReference`, `Condition`, `Procedure`, `Provenance`, plus `Task`,
`Bundle`, `OperationOutcome`. Checks are structural only (required minimal
fields, valid known/unknown statuses, transaction method/path/id
consistency, unique ids/refs, max 100 entries, closed references, no
executable or arbitrary URLs). This is not full FHIR-profile validation and
model clinical accuracy is not guaranteed; gaps surface as `DocumentReference`
or `manualReview` outcomes. `Patient.name` stays optional and no birth date
is ever computed from an age.

```sh
uv run rakathon-backend ingest-file --path note.docx --user admin --ai mock
uv run rakathon-backend ingest-file --path note.docx --user admin --ai direct \
  --patient-id trusted-patient-id --env-file .env \
  --runtime-dir /tmp/opencode --output-file summary.json
```

`ingest-file` loads `--env-file` in the same process, starts a private
ephemeral `BackendApp` (an owned `ingest-*` subdirectory, never the live
serve directory), and runs the authenticated B4 → B1 → B5 → B2 path with
ref-only IPC: raw bytes are never placed on the bus and local file paths are
never accepted over IPC. Permission is enforced before any extraction or
inference. Default output is summary only (`sha256`, `mode`,
`resourceCounts`, `manualReview`, `stored`/`storedCount`); no clinical record
is dumped. `--output-file` must not exist and is created `0600` owner-only.

Offline corpus check (17 DOCX, aggregates only, no PHI output):

```sh
uv run python scripts/verify_docx_corpus.py
```

Direct ingestion requires an explicit trusted patient association and independently
validates the provider response before persistence. See `docs/direct-ingestion.md`
for the current contract and its verification limits.

## Screening dataset (P3)

The VZP invitation archive is served as a native screening dataset, not FHIR.
One CSV row stays one invitation record with all 25 raw strings preserved;
`PERSON_ID` stays personal and `AGE_BAND` is never a birth date. Full-scan
proof (aggregates only): 1,344,556 rows, 25 columns, 508,527 distinct persons,
0 duplicate invitation ids, ~31 MB peak RSS over the 182 MB archive.

```sh
uv run rakathon-backend screening-validate --source Rakathon2026.zip
uv run rakathon-backend serve --screening-source Rakathon2026.zip
uv run rakathon-backend screening-query --runtime-dir /tmp/opencode/rak-demo \
  --user admin --filters-json '{"AGE_BAND":"65-69"}' --limit 100
uv run python scripts/verify_screening_full.py
```

`serve` without `--screening-source` (or `RAKATHON_SCREENING_SOURCE`) leaves
screening unconfigured and `screening.query` fails closed. Queries take
allowlisted equality filters plus projection with `limit 1..500`; admin and
coordinator are allowed, clinician/viewer/watchdog denied. Imports stream
through the encrypted bridge in idempotent batches (`screening-import`,
counts-only replies); `screening-init-db` creates the IRIS table on the bridge
host. Live IRIS stays NOT VERIFIED. See `docs/screening.md`.

## Direct IRIS FHIR mode (P4, opt-in)

`serve --storage iris-fhir` talks FHIR R4 directly to the exact trusted
endpoint `https://iris.racek.xyz/fhir/r4` over verified TLS. Default `mock`
is unchanged and `bridge` keeps its loopback restrictions. AI stays a
separate label (`--ai mock` by default).

```sh
uv run rakathon-backend serve --storage iris-fhir --env-file iris.env \
  --runtime-dir /tmp/opencode/rakathon-live
uv run python scripts/verify_iris_live.py --env-file iris.env
uv run python scripts/verify_iris_live.py --env-file iris.env --write-probe
```

`iris.env` (mode 0600, owner-only, git-ignored) holds only the five
`RAKATHON_IRIS_FHIR_*` keys; see `iris.env.example` for placeholders. The
direct endpoint needs `RAKATHON_IRIS_FHIR_ALLOW_DIRECT=1` and TLS
verification is forced on. IRIS FHIR create/read/update work through the
authenticated B4 → B6 → B2 path; delete exists only as test-id cleanup
inside the verification script, not as a product API. SQL, vector search,
and tasks stay `not_configured` (fail closed, never mock fallback) and the
task watchdog is off in this mode. The live script prints aggregate
codes/modes/counts plus the synthetic probe id only, never patient rows
or secrets. A dedicated least-privilege FHIR user is recommended over the
IRIS superuser. See `docs/iris.md`.

## Limitations

- B6 matrix is a MOCK; B4 maps its own token to user and never trusts caller IDs.
- B2 memory store is an explicit MOCK, not IRIS or SQLite.
- B5 default is mock labelled `mode: mock`; `serve --ai direct` needs explicit
  provider configuration and consent; a kill-switch trip disables AI entirely.
  Real model inference is NOT VERIFIED here.
- Vector anon search is `not_configured` unless a synthetic vector is seeded.
- The direct AI adapter makes outbound HTTP requests without a child-process
  listener; internal IPC uses one request/response per Unix-socket connection.
