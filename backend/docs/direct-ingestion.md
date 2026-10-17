# Direct HTTP AI and bounded FHIR R4 ingestion

The explicit `--ai direct` mode uses B5 authorization, kill switch, timeouts and
cancellation, but **no OpenCode process/session/harness**. `--ai opencode` remains
an explicit legacy mode. `--ai mock` remains the default offline demonstration.
Direct CLI/runtime imports also avoid OpenCode modules; only the explicitly
selected legacy factory imports that package. Shared timeouts are neutral.
Conversation uses a separate unstructured completion path; it never becomes a
translation transaction. No browser HTTP/UI ingestion or assistant endpoint was
added, and the read facade's assistant/ingestion capabilities remain false.

## Operator configuration

`direct-env.example` contains only non-secret Azure settings and is disabled.
Copy the desired settings into an owner-only, non-symlink 0600 environment file
outside the frontend; add `RAKATHON_AI_API_KEY` privately, never in browser env
or chat. Existing Azure base/model/key settings can be reused **explicitly**,
but are not silently discovered or enabled. Private env files only fill absent
environment values; existing process environment takes precedence.

After separate authorization for the source and target, direct mode requires:

- `RAKATHON_AI_ENABLE=1`, `AI_DISABLED=0`.
- `RAKATHON_AI_PROVIDER_KIND=azure` or `openai-compatible`.
- Explicit `RAKATHON_AI_BASE_URL` and `RAKATHON_AI_MODEL`.
- `RAKATHON_AI_AUTH_SCHEME=api-key` (Azure default) or `bearer`
  (OpenAI-compatible default); explicit server-side API key.
- `RAKATHON_AI_ALLOW_REMOTE=1` for remote HTTPS. TLS verification is mandatory;
  no redirects or environment proxy inheritance.
- Optional request timeout (1–120 seconds), and existing
  `RAKATHON_AI_KILL_FILE`. `AI_DISABLED=1` trips a running non-mock gateway.

A preexisting kill marker refuses direct configuration/startup. Both CLI app
factories receive the configured marker; B5 rechecks it immediately before every
provider dispatch, independent of watcher scheduling. The watcher checks before
its first sleep and still cancels active calls. Missing optional markers are fine;
unreadable marker state fails closed, without printing paths or file contents.

The chat/completions suffix is appended once; no deployments/api-version rewrite.
Loopback HTTP and no-auth are accepted only with explicit
`RAKATHON_AI_ALLOW_LOOPBACK=1`, a literal loopback address and explicit port.
Requests advertise `Accept-Encoding: identity`; compressed responses are rejected
rather than decoded without a bound. Maximum request/content sizes are 1 MiB,
provider response 2 MiB. No tool calls, refusal, non-stop finish, null content,
duplicate JSON keys, NaN, Markdown extraction, JSON repair or fallback format.
Providers must support the supplied strict JSON-schema response format or fail.

## Translation contract and local gates

The exact provider object has only:

```json
{"status":"manual-review","bundle":null,"issues":[{"code":"missing-context","resourceType":null,"detail":"Synthetic missing source context"}]}
```

`status` is complete, incomplete or manual-review. `bundle` is a nonempty
transaction or null. Every provider object is closed (`additionalProperties:
false`), with all declared properties required and optional values explicitly
nullable. See `b1/schema.py` for the fixed supported field subset and issue codes.
Only declared optional nulls are omitted before FHIR validation. Required nulls
or unknown fields reject the entire response; there is no silent salvage.

Eight clinical entry types: Patient, Condition, Observation, DiagnosticReport,
DocumentReference, ServiceRequest, Procedure, Provenance. Bundle and validated
OperationOutcome are envelopes/outcomes, never clinical transaction entries.
No arbitrary FHIR types or unrestricted nested extensions are accepted from AI.

Independent local JSON-schema validation precedes exact R4 model validation:
`fhir.resources==6.4.0` (FHIR 4.0.1), `pydantic[email]>=1.10.26,<2`, and
`jsonschema>=4.26,<5`. These were tested on Python **3.14.8**. R4B/R5 packages
are not substitutes. Application guards separately enforce known status/intent
codes, strict raw JSON types (no string/bool/number coercion), required fields,
canonical IDs, transaction requests and reference closure. Model validation
never supplies stored clinical defaults: the original validated values, zero,
false, date precision and literal source text are retained. Technical metadata
is added separately and the final tagged bundle is validated again.

This is a deliberately bounded subset, **not full terminology/invariant validation
or a guarantee of clinical truth or source-extraction fidelity**.

## Partial outcomes and ownership

- **complete:** nonempty valid transaction, no issues/material omissions.
- **incomplete:** nonempty independently valid safe subset and structured issues;
  `needsReview=true`, `writeEligible=true`. Every stored resource receives
  `meta.tag` with system `urn:rakathon:ingestion-status`, code `incomplete`.
  Clinical verification/status is never changed to express incompleteness.
- **manual-review:** no safe subset; null bundle, issues, zero clinical writes.

Missing required clinical facts must cause the provider to exclude that fragment
and report an issue. A valid source DocumentReference may retain recoverable
context when association and required facts are known; the application does not
invent such a resource or repair an invalid response. Refused/truncated/invalid
responses are errors, not eligible partial successes.

Direct ingestion requires a trusted, explicit `--patient-id`/B1 patientId context.
No context means manual-review without writes. The provider must return exactly
one associated Patient with that ID; names alone cannot select an identity.
Every clinical subject must match it; all references/dependencies must be closed
within the atomic subset. No implicit existing-patient lookup, merge or fallback.

The import source is the original file's SHA-256 URN, including original DOCX
bytes before text extraction. Every resource gets this source metadata. Other
resource IDs are remapped to source-scoped technical IDs and references rewritten
without changing facts. B2 independently checks source/tag/context/association
and rejects existing IDs. Reserved ingestion tags and resource-level SHA-256 source
metadata require validated import context even if a caller omits the ingestion
envelope. Plain writes carrying these reserved markers are rejected; ordinary
untagged standalone FHIR writes remain supported. Import validation and persistence
use the same deep-copied payload snapshot. Import PUTs additionally use `ifNoneMatch: "*"`;
MemoryStorage enforces create-only atomically, and an actual FHIR target must
honor the standard transaction precondition. Unsupported/failed preconditions
must fail, never retry as unrestricted overwrite. Live IRIS conditional-write
support remains **unverified**. Live imports are actively disabled in the CLI and
B2 import boundary, not merely described as needing authorization.

This initial path deliberately refuses reimports/existing Patient conflicts;
it does not solve an existing-patient update/merge workflow. No guessed Patient
or orphan resource is created to work around missing association.

B1/B4 return translation status/issues/needsReview/writeEligible, proposed counts,
source provenance, `storedCount=0` and `persistence=not-requested`; translating
alone does not persist. The CLI separately performs one authenticated B4→B2
transaction and reports actual stored counts only after successful confirmation.
Valid incomplete data can be stored despite needsReview. Storage failure or
unconfirmed counts yields a nonzero exit, never complete/count success.
CLI stdout omits stored resource IDs and free-form provider issue details on the
direct path; structured issue codes/types and aggregate counts flag the sender.

## Commands and deployment status

```sh
uv run rakathon-backend serve --ai direct --storage mock --env-file .env
uv run rakathon-backend ingest-file --ai direct --storage mock --env-file .env \
  --path synthetic-source.txt --user admin --patient-id synthetic-1
```

`ingest-file` uses an ephemeral in-memory store, cleaned at exit. Its reserved
`--storage iris-fhir` choice currently fails with live_import_not_configured before
input/provider processing. B2 also rejects non-mock import persistence. A separate
review/authorization and conditional-write proof are required before enabling it.
Nothing seeds, resets or imports on startup. No real corpus was sent externally.

Offline tests (no provider/DB calls):

```sh
python -m pytest tests/test_direct_http.py tests/test_direct_ingestion.py \
  tests/test_direct_cli.py tests/test_r4_ingestion_policy.py \
  tests/test_ingestion_safety_fixes.py tests/test_direct_import_isolation.py -W error -q
```

The running backend virtual environment/services were **not upgraded/restarted**.
Locked dependencies and evidence are in an isolated test environment. A controlled
dependency installation/restart is still pending. The current read facade does
not project the controlled ingestion tag; a separately approved projection/client
follow-up is needed before displaying imported incomplete data as fully covered.
