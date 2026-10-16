# Handoff — Rakathon backend (B1–B6) + real-data work

## Objective
- Implement `rakathon2026/backend` per authoritative `rakathon2026/architecture.md` B1–B6.
- Python-only, modular, no frontend. CLI mock only.
- Make it work with root `vzp_data`: DOCX via B1 extract + B5/OpenCode + Azure, screening CSV as native screening dataset.
- Fix known `fhir.search` B4/B6 auth mismatch.

## Requirements
- English-only output.
- Backend in `../rakathon2026/backend`, not `prep/backend`.
- Python 3.13 via `uv`. Stdlib-first + `httpx 0.28.x` + `cryptography`. Optional `intersystems-irispython` extra.
- Authenticated Unix-socket JSON-RPC between blocks. No raw blobs on bus, only `ipc-blob://` refs.
- Coding gates enforced: zero `#` comments preferred, if used single-line + allowed kaomoji `:3 :> :< >< >w< :p` alternating, max 1/12 LOC. Max 350 LOC per authored file.
- Imports at top. Strict mypy, ruff, `pytest -W error` clean.
- Commits allowed to this repo, none made yet. If committing: no description, message all-lower or all-UPPER + trailing kaomoji.
- Do not touch root `architecture.md`, `context.md`, `vzp_data/`. Do not print secrets, keys, patient rows, clinical text.

## Decisions
- B1–B6 in `rakathon2026/architecture.md` is sole truth. `prep/` B1–B7 superseded. No MDT/quorum/Provenance API required.
- B2 thin IRIS wrapper. B5 sole AI gateway, orchestrates external OpenCode. B6 MOCK `matrix.json` allowed.
- E2EE: trusted Python crypto bridge beside IRIS. Nginx sees ciphertext only. B2 narrow egress exception to bridge allowed. Bridge + IRIS plaintext is trusted boundary.
- Azure AI exception: user approved `Allow all. Azure is trusted.` B5 may send test/all docs to Azure via HTTPS + `api-key`. IRIS bridge stays app-encrypted.
- Azure target: exact `https://apim-rakathon-q7146n.azure-api.net/openai/v1`, deployment `gpt-6-luna-dz-eu`, `POST /chat/completions`, literal `api-key` header, `model` = deployment. No `/deployments` rewrite, no `api-version`.
- OpenCode pinned `v2.0.31`. The P1 builder (`b5/opencode/validation.py`,
  verified against the pinned binary) writes config file shape
  `provider.<pid>.{npm, name, options(baseURL, headers), models}` plus
  singular `permission: "deny"`, a `policies` deny list, and `model:
  "<pid>/<name>"`. The `/api/session` create body separately uses plural
  `permissions: [{action, resource, effect}]` with `model: {providerID,
  id}`. Provider id `rakathon-azure`, never `azure`. Header `api-key:
  {env:RAKATHON_AI_API_KEY}`, no Bearer.
- Screening CSV stays screening data. No invented names, DOB, referrals. DOCX: local OOXML extract in B1, faithful FHIR via B5, `DocumentReference` / `manualReview` fallback, never forced `ServiceRequest`.
- P1 → P2 → P3 sequential writers only.

## Work State
### Completed
- S0 foundation: contracts, authenticated UDS, config, B6, 37 tests.
- S1 offline six-block demo: B1-B6, mock AI, watchdog, router, CLI `demo/serve/client/health`, 74 tests.
- S2 bridge: Fernet `POST /rpc`, replay cache, `EncryptedBridgeStorage`, IRIS FHIR/SQL/vector adapters, atomic transactions, 121 tests.
- S3 OpenCode: isolated `serve`, V2 `/api/session` + `/generate` + `/interrupt` + `DELETE`, kill-switch, 203 tests.
- S3b actual-binary fix: `/api/session` health, `model:{providerID,id}`, IPv6 brackets, isolated netns fake-provider smoke, 209 tests.
- 5 oracle reviews PASS, then S4 hardening: task forgery/ACK membership, per-user visibility, `(source,requestId)` pending bounds, FHIR kinds, per-server bridge dispatcher, socket timeout, `trust_env=False`, atomic 0600 secret files, real `iris.dbapi.connect`, vector split creds, CAS ACK, loopback-only FHIR, liveness scope. 260 tests.
- Post-fix 5 reviews PASS.
- `vzp_data` verification: 260 baseline PASS, no importer. CSV 1,344,556 rows / 25 cols / 182 MB. First100 as JSON → 100 manual-review, 0 Bundles. 17 DOCX true MIME rejected, extracted text → 17 manual-review. Found `fhir.search` denied at B4/B6.
- P1 Azure: exact-origin allowlist, consent + key gating, `--env-file`, AI timeouts 180/185/190/200/205s, real-binary fake-header proof, one live `Reply with OK` → `mode:opencode`. 303 tests PASS. `demo` unchanged mock.

### Final repair completed
- Final-review repair DONE (sole writer, no live calls). Gates: 399 pytest PASS
  (`-W error`, 29 new guard/width tests), ruff check + format clean, mypy
  `src tests scripts` clean (113 files), compileall clean, demo clean.
  Fixes: (A) `samples` typed + full scripts mypy; (B) zero nested/late imports
  across src/tests/scripts (importlib factory, hoisted shutil/MAX_BATCH/
  archive_store/os/iter_validated_rows, test + script bootstrap removed);
  (C) shared `check_resource`/`check_bundle` enforced at B2Service direct +
  transaction, MemoryStorage, bridge protocol/client pre-network, and IRIS
  FHIR adapter pre-request, with B2/B4/store/bridge regressions + valid
  standalone Patient reference persisted; (D) `INVITATION_ID` width 32->64
  (`INVITATION_ID_WIDTH`) with longest-legal (INV+32 digits) preservation +
  DDL test, fake DBAPI only, non-destructive migration noted in
  docs/screening.md + docs/iris.md. Full-CSV (1,344,556 rows / 508,527
  persons / 0 dupes / ~31 MB RSS) and live-Azure evidence reused unchanged
  (no reader/schema semantics change; width is DDL-only expansion). No
  commits/push made; the user always commits and pushes.

### P4 completed
- P4 direct IRIS FHIR mode: IMPLEMENTED, offline gates and live proof
  PASS. `serve --storage iris-fhir` (opt-in, default mock unchanged,
  bridge loopback unchanged) with `FhirOnlyStorage` delegating FHIR
  create/read/update to `DirectFhirAdapter` against the exact trusted
  `https://iris.racek.xyz/fhir/r4` (verified TLS forced,
  `RAKATHON_IRIS_FHIR_ALLOW_DIRECT=1` only honored in this mode,
  bridge-serve never opts in). SQL/vector/tasks fail closed
  `not_configured`, watchdog off, screening archive still separate local
  mount. `_summary=count` reports the server Bundle.total; normal search
  keeps legacy `total=len(items)` plus additive `serverTotal`. Offline:
  445 pytest PASS (`-W error`), ruff check + format clean, mypy
  `src tests scripts` clean, compileall clean, demo clean, import/comment/
  filesize audits clean. Live proof via `scripts/verify_iris_live.py`
  (read-only first, then `--write-probe` synthetic lifecycle with direct
  DELETE cleanup) passed; all five final reviews PASS.
- P4 live proof: DONE, rc=0 both phases, all through the authenticated
  frontend UDS to B4 to B6 to B2 path (no direct-provider fallback).
  Read-only: mode/clientMode/appMode iris-fhir, /metadata 200
  fhirVersion 4.0.1 over enforced verified TLS, _summary=count Patient
  countTotal 6 serverTotal 6 entryCount 0 (server total kept despite empty
  entries). Write probe, single owned synthetic Patient only, pre-write
  GET 404, no other resources or transactions: create PUT plus backend
  readback marker (urn:rakathon:verification identifier,
  SYNTHETIC-LIVE-PROBE tag, active false, Synthetic Probe Rev1), update
  PUT plus readback (Synthetic Probe Rev2), direct DELETE 204 after owned
  fetch check, direct confirm GET 410, backend post-delete tombstone
  noted honestly. Probe id rakathon-probe-3d03eb20421e495384ef1f2ccf6cd74a
  (non-PHI) deleted; FHIR soft-delete history may remain, not claimed
  purged. Output was aggregates/codes/modes/counts only. iris.env is
  private 0600, git-ignored, and absent from git status; temp live
  runtimes removed. All five final reviews PASS after comment-only cleanup;
  46 affected tests and full mypy/Ruff rechecked; 445-test full-suite evidence remains valid.

### Authentication completed (this isolated worktree)
- Authentication integration is implemented in this worktree and fully
  gated (532 pytest PASS with `-W error`, ruff check + format clean, mypy
  `src tests scripts` clean for 156 files, compileall clean, demo clean).
  Frontend wiring is COMPLETE per the reconciled frontend report. A sole-writer
  security-repair lane then fixed six bounded findings (session CAS retry,
  IRIS atomic rate/prune, proxy-key safe open, Host allowlist, authorize
  envelope binding, inert-watchdog doc) with regression tests, followed by final
  bounded repair: malformed usernames map to generic 401 with dummy work plus
  rate cover before hashing, active logout propagates store outage as 503 without
  clearing the cookie, nested test imports hoisted, and IRIS/SQLite rate state
  moved to UNIQUE (scope, key, slot) slots safe at READ COMMITTED with
  reservation-id compensation. All five final closure reviews PASS: comments,
  warnings/toolchain, imports, file size, and correctness/security. The parent
  also reran frontend `npm run check`: 363 tests, types, zero-warning lint,
  production build, and seven-file mock-exclusion check PASS.

### Phase B completed (this worktree, sole writer)
- B7 UDS `auth.login/resolve/logout` (`b7/handler.py`) on `web:auth`-only
  registry, proprietary kinds, closed bounded payloads, `asyncio.to_thread`
  auth operations. Local in-process store port, no new B2 socket.
- `web:auth` trusted propagation: B4 `web_sources` default-deny plus
  `_handle_web` and shared `_authorize_and_route`; legacy `frontend:<user>`
  checks preserved exactly; `web_envelope()` rejects authority fields.
- B6 optional `RoleResolver` plus B2/B4 optional `is_privileged`; fail-closed
  callbacks, static defaults unchanged, watchdog stays service-only.
- HTTP edge (`web/config.py|router.py|edge.py|server.py`): login/session/
  logout routes, proxy-key gate on all requests, exact Origin plus CSRF on
  writes, `__Host-` vs loopback cookies, 16 KiB body cap, loopback bind only,
  no request logging, default authenticated clinical 503, unauth 401 first.
- Runtime `BackendApp(auth=bundle)` via `runtime/auth_bundle.py`; six-service
  default untouched. CLI `auth-init|auth-user-add|auth-user-disable|auth-serve`
  (`runtime/auth_cmds.py|auth_serve.py`) with 0600 secrets and no seeding.
- New tests: `tests/test_auth_http.py` (7 live-127.0.0.1 HTTP tests),
  `tests/test_auth_phaseb.py` (5 full-IPC tests). Full gates green.
  Pre-existing ruff check (3 in `runtime/ingest.py`) and format
  (`application.py`, `bridge_cmds.py`, `commands.py`) repaired mechanically.
- Frontend login/session UI and five final reviews: COMPLETE. Pending separately:
  the other developer's clinical read projection facade
  (`GET /api/v1/session|workspace|cases`) and integration into the main checkout.

### Connector final (this worktree, sole writer)
- HTTP auth callbacks traverse the real B7 UDS wire via
  `B7SocketClient(runtime_dir, tokens["web:auth"])` (`b7/client.py`,
  `AuthenticationPort`/`AuthSessionPort`, verified proprietary replies,
  code-based errors only). `auth-serve` still builds `AuthService` for the B7
  backend and B6 resolver but never calls it from HTTP; missing listener or
  wrong token is login/session/logout 503. HTTP worker drain moved to
  `asyncio.to_thread` with bounded join before `app.close()`.
- `make_b4_dispatch` stub removed; `B4ActionClient.call(identity, action,
  payload)` forwards the exact `USER_ACTIONS` entry via `web_envelope`.
- New tests `test_auth_connector.py` (5), `test_auth_connector_wire.py` (8),
  `test_auth_connector_b4.py` (6): 532 pytest PASS (`-W error`), ruff and
  mypy clean. All five final closure reviews PASS; frontend checks freshly PASS.

### Blocked
- Live FHIR create/read/update verified. SQL/vector/task storage and the encrypted bridge remain unverified live.

## Next Move
1. P2 DOCX: DONE. `b1/docx.py` stdlib extract + caps, shared `common/fhir.py`
   allowlist (B1/B2-mock/IRIS/bridge), `ingest-file` CLI (ephemeral runtime,
   ref-only IPC, summary-only output), provenance `meta.source`
   `urn:sha256:<original>`. Evidence: 349 tests PASS (46 new), ruff + mypy +
   compileall + demo clean, offline extraction of all 17 corpus DOCX (0
   failures), 2 bounded live Azure conversions (clinical → 14 stored
   Patient/Condition/Observation/DiagnosticReport; admin → single
   DocumentReference). Structural checks only; fidelity not guaranteed.
2. P3 CSV + `fhir.search`: DONE, see item 3 evidence. Commands:
   `screening-validate --source ZIP`, `serve --screening-source ZIP`,
   `screening-query` (aggregates by default), `screening-import --batch-size`,
   `screening-init-db`, plus `scripts/verify_screening_full.py` (opt-in).
3. Final gates and all five post-repair/P4 reviews: DONE, PASS. Live FHIR verified; SQL/vector/tasks remain unverified.
   P3 CSV + `fhir.search`: DONE. `b2/screening/{schema,reader,ports,archive}.py`
   streaming validation plus archive MOCK store, `b2/iris/screening_sql.py`
   batch IRIS adapter, `screening-validate/query/import/init-db` CLIs,
   `serve --screening-source`, bridge `screening.import/query`, B6
   `fhir.search→fhir.read` canonical alias with `screening.query` matrix
   (admin/coordinator only). Evidence: 370 tests PASS (21 new), ruff + mypy +
   compileall + demo clean, full-dataset `screening-validate` reproduces
   1,344,556 rows / 25 cols / 508,527 persons / 0 duplicate invitations at
   ~31 MB peak RSS, first/mid/end digests recorded, authenticated B4→B2
   admin query matches the direct adapter with clinician denied and
   `fhir.search` allowed through the real app. IRIS adapter proven with
    offline fakes only; live FHIR writes were separately verified in P4 above.

## Relevant Files
- `/mnt/870Ext/sync/programming/rakathon/rakathon2026/architecture.md`: B1–B6 truth, 190 lines, 1 pre-existing E2EE line diff.
- `/mnt/870Ext/sync/programming/rakathon/rakathon2026/backend/`: implementation, `pyproject.toml`, `README.md`, `docs/contracts.md`, `docs/iris.md`, `docs/encryption.md`, `docs/opencode.md`, `azure-env.example`.
- `/mnt/870Ext/sync/programming/rakathon/rakathon2026/backend/.env`: private 0600 ignored, holds Azure key only. Never read via file tool, never print.
- `/mnt/870Ext/sync/programming/rakathon/rakathon2026/vzp_data/Rakathon2026.zip`: member `Rakhaton2026.csv`.
- `/mnt/870Ext/sync/programming/rakathon/rakathon2026/vzp_data/rakathon_final_all/`: 17 DOCX + 1 PPTX, 13 patient docs = 1 case + 4 admin.
- Git: `M architecture.md`, `?? backend/`, HEAD `aea38a1`. No commits made.

## Important Context
- Runtime: Python 3.13/3.14, `uv 0.12.14`, OpenCode v2.0.31, AF_UNIX ok. No IRIS drivers installed locally.
- Live IRIS FHIR at `https://iris.racek.xyz/fhir/r4`: authenticated read/create/update verified with one synthetic Patient, deleted afterward. SQL still needs a separate superserver connection and is unverified live.
- `fhir.search` authorization mismatch: FIXED by B6 canonicalizing to `fhir.read` before checking permissions; real-app regression verified.
- Limits: mock default, replay process-local restart-unsafe, no true anonymization, B6 mock, no OCR, no PDF ingest, health = `authenticated-ipc-liveness`, deps not checked.
