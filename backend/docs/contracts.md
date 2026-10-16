# Contracts (S1 runtime)

Wire envelope keys: `version, requestId, correlationId, source, target, action,
dataKind, payload, userId?`. `version` is exactly `1`.

## Physical vs logical

Physical transport is Unix sockets plus token registry. Logical connectors are
`DataKind` values (`fhir`, `proprietary`, `metadata`) carried inside envelopes.
One socket multiplexes logical connector IDs: `action` plus `dataKind` select
the logical connector. Replies preserve `requestId` and `correlationId`.

## Auth

Token registry maps token to service name. Server rejects mismatched
`envelope.source`. Unicode tokens fail closed. `request.target` must equal the
server service name. `response.target` must equal the client source.
B6 `authorize` expects `{userId, action}` and allows only listed sources.
Every service checks B6 per end-user action and fails closed.

## DataKind rules

FHIR resources use `fhir`. Reminders and raw text use `proprietary`.
IDs, status, and counts use `metadata`. Task records link patients, so full
task payloads stay `proprietary`; only id/status summaries are `metadata`.
This task-classification choice is a runtime interpretation. The authoritative
file `architecture.md` is unchanged.

Request kinds (what the caller sends) versus response kinds (what comes
back) differ on purpose:

- `fhir.write` requests and responses are `fhir`. A `fhir.write` arriving
  with `metadata` kind is rejected as misclassified: metadata connectors
  must never carry PHI.
- `tasks.write` requests and responses are `proprietary` (the payload
  carries `patientRef` linkage).
- `tasks.read` requests are `metadata` (id-only lookup arguments);
  responses are `proprietary` (full task records, server-filtered to the
  caller's membership; only policy-derived privileged users such as
  admin/coordinator/watchdog read the whole queue).
- `tasks.ack` responses are `proprietary`; the ack identity is always the
  envelope user and must be a task member.
- `fhir.read`/`fhir.search` requests are `metadata`; FHIR responses are
  `fhir`.
- `screening.query` requests are `metadata` (allowlisted filters, projection,
  limit, offset); responses are `proprietary` (bounded native rows).
- `ai.complete`, `ingest`, and both vector searches are `proprietary`.
- `reminders.read` responses are `proprietary` and carry only opaque
  task identifiers plus reason; the count-only shape is metadata-safe.
- `health` is transport liveness only: responses carry
  `scope: liveness` and `deps: not_checked` and never claim that IRIS or
  AI dependencies are usable. `health` without a running config reports
  `DOWN` instead of inventing a fresh app.

Shared mapping lives in `common/kinds.py` and is used by the B4 router,
the CLI client, and the demo so request kinds cannot drift per caller.

## Blobs

Opaque IDs, scheme `ipc-blob://b1/<id>`. Allowlist `text/plain`,
`application/json`, plus the DOCX MIME
`application/vnd.openxmlformats-officedocument.wordprocessingml.document`.
PDFs return a structured manual-review error without OCR. DOCX originals are
resolved by B1 to a bounded derived `text/plain` blob; only the derived ref
travels to B5 and the derived copy is deleted after translation. Fetch
resolves only internal references, never paths or URLs.

## Actions

- `ingest` (B4 to B1, proprietary, needs `bytesRef` plus purpose; DOCX refs
  extract locally first and reply with `sourceHash`/`sourceUrn` aggregates)
- `fhir.read` (`resourceType`, optional `id`, other string params filter)
- `fhir.search` (alias of read permission, same shape; replies carry legacy
  `bundle.total = len(items)` plus an additive `serverTotal` when the store
  reports one, and an explicit `_summary=count` request reports the server
  total instead)
- `screening.query` (`filters`, `projection`, `limit 1..500`, `offset`;
  admin/coordinator only, native rows, never FHIR)
- `fhir.write` (Bundle or single resource)
- `tasks.read`, `tasks.write`, `tasks.ack` (ack identity is the envelope user)
- `vector.anonymized.search`, `vector.patient.search` (anon denied unless a
  seeded SYNTHETIC vector exists; patient wraps matches in a Bundle)
- `ai.translate`, `ai.complete` (B5 gateway, mock only, `mode:mock`)
- `watchdog.tick` (watchdog user only, returns metadata count)
- `reminders.read` (local to B4, filtered), `reminders.deliver` (B3 to B4)
- `health` (transport-level, identity metadata only)

## Bridge and OpenCode notes for later writers

- `b2/ports.py` defines `Storage`: `fhir_write`, `fhir_read`, `fhir_search`,
  `tasks_write`, `tasks_read`, `tasks_ack`, `vector_search`. Bridge implements
  this with IRIS FHIR REST plus SQL tasks plus vector adapters.
- `b5/gateway.py` defines `AIAdapter`: `translate(data, content_type)`,
  `complete(data, content_type)`, `close()`. OpenCode adapter spawns managed
  subprocesses there. `KillSwitch` defaults with remote disabled.
- `B1Service`, `B2Service`, `B3Service`, `B4Router`, `B5Gateway` accept
  injected `auth_check`, blob, store, adapter, and downstream callables.
