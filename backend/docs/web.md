# Read-only development facade, contract v1

Run from `backend/` using Python >=3.13 and the locked environment:

```sh
uv run rakathon-backend web-serve --env-file iris.env \
  --runtime-dir runtime/web --port 8765 \
  --proxy-key-file runtime/web-proxy.key \
  --frontend-origin http://127.0.0.1:5173 \
  --frontend-origin http://127.0.0.1:5174 \
  --frontend-origin http://localhost:5173 \
  --frontend-origin http://localhost:5174 \
  --frontend-origin http://10.0.0.103:5174
```

Only literal `127.0.0.1` binding is supported. Additional origins, including
Tailscale origins, must be explicitly supplied; no automatic wildcard allowance.
The resident BackendApp and all UDS clients share the CLI's one owned asyncio
loop. At most eight HTTP worker threads submit to that loop, with four concurrent
authenticated backend reads. No per-request event loop or direct storage bypass.
Shutdown closes HTTP, BackendApp sockets/services and its HTTP-backed store.

## Security boundary

This is **single-user development**, not staff/patient authentication. Any client
allowed to reach the LAN frontend can use the fixed backend **viewer** identity.
UI role selection does not change backend authorization. The three GET
routes below remain available; the optional assistant POST is described below.
There are no writes, generic RPC, uploads, automatic AI calls, URL
fetchers, bridge secrets, encrypted bridge endpoint or automatic database seeds.
IRIS errors never activate mock data.

The proxy key file is atomically published without replacement, owner-only 0600,
regular, single-link and non-symlink. Unsafe existing files are rejected without
overwrite; key files inside `app/` are rejected. Do not print its contents.
The server-side Vite proxy must read this file and **overwrite** the incoming
`X-Rakathon-Proxy-Key` header. Never put it in a VITE_* variable or browser code.
It is a proxy capability, not end-user authentication.

Every request requires that header, constant-time comparison, and exactly one
Host equal to `127.0.0.1:<facade-port>` or `localhost:<facade-port>`.
Origin, if present, must exactly match an explicit configured origin.
Forwarded/X-Forwarded-Host/X-Original-Host are rejected, never trusted. Duplicate
security headers, query strings (even empty), encoded paths, unsupported methods,
transfer encoding, Expect, and nonzero/malformed Content-Length are rejected.
No CORS headers are returned. All responses, including errors, are `no-store`.
Request logging is disabled; no patient IDs, raw paths, tokens or payloads are
logged. Limits: 2 KiB request line, 16 KiB accepted headers, stdlib's bounded
parser hard limits, eight workers plus bounded listen queue, 5s socket timeout,
7s backend-call timeout, 35s HTTP submission timeout, 1 MiB JSON response.
Disconnect/HTTP cancellation does not prove already-running provider work was
cancelled. Existing synchronous upstream calls remain bounded by adapter timeouts.

## Optional POST /api/v1/assistant (disabled by default)

The operator must explicitly set `RAKATHON_WEB_ASSISTANT_ENABLE=1`,
`RAKATHON_AI_ENABLE=1`, `AI_DISABLED=0`, `RAKATHON_AI_ALLOW_REMOTE=1`,
`RAKATHON_AI_PROVIDER_KIND=azure|openai-compatible`, `RAKATHON_AI_BASE_URL`,
`RAKATHON_AI_MODEL`, `RAKATHON_AI_AUTH_SCHEME` and server-only
`RAKATHON_AI_API_KEY` before using the same `web-serve` command above.
Private env loading fills absent process variables only; explicit process OFF
overrides remain OFF. Configuration errors fail startup, never select another
provider/auth scheme. The intended public base is
`https://apim-rakathon-q7146n.azure-api.net/openai/v1`, model
`gpt-6-luna-dz-eu`. No credential is supplied by this document.

Auth scheme `api-key` sends only `api-key`; `bearer` sends only
`Authorization: Bearer …`; `subscription-key` (or exact
`Ocp-Apim-Subscription-Key`) sends only
`Ocp-Apim-Subscription-Key`. No guessing/fallback. Unauthenticated test mode is
not accepted by web startup. `RAKATHON_AI_REQUEST_TIMEOUT` defaults to 60s and
must not exceed 60s here. `AI_DISABLED=1` or the existing
`RAKATHON_AI_KILL_FILE` disables dispatch and capability; no B2 safety changes.
Session assistant capability requires configured direct mode, healthy reads and
an untripped local gateway. No provider request is made to check health.

POST requires an explicit allowed Origin and exact JSON content type, one
positive Content-Length <=16384 bytes, no transfer encoding/Expect, duplicate
keys/constants or unknown fields. Body: `{role,text}` for general questions (no
patient reads), or `{role,text,caseId}` for the currently selected patient.
`caseId` matches `^[A-Za-z0-9.-]{1,64}$`. Roles:
`koordinator|pacient|lekar|mdt` affect presentation only, not data access.
Limits: input1000/output12000 characters. No history/tasks/persistence.
Client-supplied `context`, `binding`, `userId` and other unknown keys are rejected.
Only one assistant submission at a time (429 when busy); facade deadline80s,
HTTP wait85s, browser deadline90s. Browser abort suppresses stale replies but
does not prove IPC/provider immediate cancellation; existing B5 kill/deadline
bounds remain active. Errors contain stable safe codes/messages only.

Conversation completion alone retries HTTP429 up to three total attempts. It
requires exactly one valid Retry-After header (nonnegative integer seconds or
timezone-qualified HTTP-date). The response is closed before waiting. All attempts
and waits share the configured provider request deadline (at most60s here); a
delay that cannot fit is never shortened or retried early. Missing/malformed
headers or exhausted attempts fail safely as internal `ai_rate_limited`, retaining
the facade's generic503 unavailable response. Other HTTP errors, timeouts and
ambiguous network failures are not retried; ingestion translation is unchanged.
Waiting is cancellable and checks the operator kill guard at most every0.1s and
again before dispatch. The existing frontend loading state remains in flight;
there is no invented countdown or provider error-body disclosure.

For an explicitly activated local deployment, an owner-only0600 ignored combined
configuration may be stored at `backend/runtime/web-assistant.env`, merging the
existing IRIS settings with explicit assistant settings. Pass that file to
`web-serve --env-file runtime/web-assistant.env`; do not add it to Git or expose it
through the frontend. Process environment still takes precedence, including
explicit operator disablement. Authentication remains the explicitly configured
scheme, never a fallback.

### Full authorized selected-patient record egress

Sending `caseId` authorizes server assembly and **egress of the full available
record to the configured Azure/direct AI provider**, including identifiers,
names, narratives, notes, conclusions and upload text. This is not anonymized or
limited to metadata. The server first performs the same Patient read used by
case GET, through B4/B6/B2 under the authenticated **human's identity**. Failure
stops before compartment collection, upload access or AI dispatch. There is no
new patient-ownership mapping. The `web-assistant` service principal still has
ONLY `ai.complete` permission and never performs patient reads.

Full unprojected Patient plus patient-scoped searches collect Condition,
Observation, DiagnosticReport, DocumentReference, Procedure, MedicationRequest,
MedicationStatement, AllergyIntolerance, Encounter, ServiceRequest, CarePlan,
Immunization, FamilyMemberHistory, ClinicalImpression, CareTeam, Goal, Specimen,
ImagingStudy, Composition and QuestionnaireResponse. The adapter does not expose
`$everything`; per-type searches use its existing same-origin/base-boundary,
cycle-protected pagination (50/page, at most10 pages, 500 resources/type).
Unsupported400/404 types and failed collections appear in the timestamped
manifest; incomplete pages are never represented as complete. Read-only type
allowances do not expand FHIR writes. Each type reply stays below the existing
1MiB B2 reply limit. Collection size-limit failures produce413, not truncation.

Inline base64 UTF-8 `text/*` and `application/json` attachments in
DocumentReference and DiagnosticReport are decoded within bounds. Non-text
attachments are marked `binary, not readable`; external attachment URLs are
never fetched. The complete original FHIR resources are retained as well.
All owners' uploads for the authorized case are included, never other cases:
validated transcription is labeled `transcription (unverified)`, approved
review bundles `approved`, and available drafts `pending draft`. Collection is
read-only and does not initialize or transition review state.

The prompt contains safety instructions, manifest, canonical JSON resources,
document text, uploads and the question. Patient data is untrusted, not
instructions; answers must cite included resource types/ids or upload ids and
state missing information. The assistant is informational, not a prescriber.
The final UTF-8 prompt limit is `ASSISTANT_MAX_CONTEXT_BYTES` (default900000,
configurable downward, hard maximum900000). Over-budget requests return413
`context_too_large` without AI dispatch or silent truncation. Encoded JSON frame
sizes are checked too. IPC and direct-provider request defaults/hard maxima are
4MiB to accommodate escaping. No prompt/record is persisted by this endpoint.

Case GET no longer adds `assistantPreview`; bindings and snapshot TTL are gone.
Successful response: `{provenance:"server",text,sources,coverage}`. `sources` is
at most50 included `ResourceType/id` or `upload/id` strings (an inclusion list,
not proof every item was cited by the model). `coverage` has `status`
(`general|complete|partial`), resource/upload counts and `failedTypes`; selected
records also report `unreadableAttachments` and
`uploadsWithUnavailableArtifacts`. Plain-text completion has no ingestion FHIR
response_format. The UI renders plain text, not HTML/tool actions.

## GET /api/v1/session (HTTP 200)

```json
{
  "version": 1,
  "access": "single-user-development",
  "storage": "iris-fhir",
  "capabilities": {
    "workspaceRead": true, "caseRead": true,
    "tasks": false, "vectors": false, "ingestion": false,
    "screening": false, "assistant": false
  },
  "health": {"ipc": "up", "database": "up"}
}
```

Health values are `up` or `down` after independent checks (clients may reserve
`not-checked` for not-yet-fetched state). IPC is authenticated B4 liveness;
database is up only after a separate viewer B4 -> B6 -> B2 authenticated
Patient `_summary=count` returns a nonnegative integer serverTotal in iris-fhir
mode. Metadata reachability alone never establishes database health.

## GET /api/v1/workspace (HTTP 200 or 503, same shape)

Entirely synthetic contract example:

```json
{
  "version": 1, "fetchedAt": "2026-10-16T12:00:00+00:00",
  "patients": [{"patientId": "synthetic-1", "label": "Synthetic Example", "birthDate": null}],
  "coverage": {"status": "complete", "serverTotal": 1, "reason": null}
}
```

Fixed initial Patient search `_count=50`; validated opaque next links are collected
server-side within the budgets below, with no browser paging API. Label derives only from
the first supplied name's text or given/family, otherwise null. No age, disease,
workflow, priority, next step or dates are invented. `fetchedAt` means facade
fetch time, not source issue time or proven historical local availability.

Failure/truncation/invalid resource returns HTTP 503 with `patients: []`,
`coverage.status: "unavailable"` and the typed reason below.
serverTotal is preserved if the authenticated response exposed it, else null.
An optional FHIR total may be an estimate: it is preserved separately from actual
receivedCount and is never assumed equal to collection length. The frontend must parse this 503 shape,
not treat its empty patients array as a successful empty workspace.

## GET /api/v1/cases/{patientId} (HTTP 200)

FHIR ID: `[A-Za-z0-9.-]{1,64}`, case sensitive. Exact Patient read must return
exactly the requested type and ID. Absent Patient is 404, not another/default
case. Invalid/mismatched Patient response is 503. Independent section searches
use only fixed resource types, `patient=Patient/<id>` and `_count=50`.
Every result must have a subject/patient reference exactly `Patient/<id>`;
missing, conflicting, external/absolute or wrong references invalidate that
section even if the upstream server ignored the search filter.

Entirely synthetic contract example (abbreviated items, complete section keys):

```json
{
  "version": 1, "fetchedAt": "2026-10-16T12:00:00+00:00",
  "patient": {"resourceType": "Patient", "id": "synthetic-1", "name": [{"given": ["Synthetic"], "family": "Example"}]},
  "sections": {
    "conditions": {"status": "complete", "items": [], "reason": null, "serverTotal": 0},
    "observations": {"status": "complete", "items": [{"resourceType": "Observation", "id": "synthetic-obs", "subject": {"reference": "Patient/synthetic-1"}, "status": "final", "code": {"text": "Synthetic test"}, "valueQuantity": {"value": 7, "unit": "test"}}], "reason": null, "serverTotal": 1},
    "diagnosticReports": {"status": "unavailable", "items": [], "reason": "upstream_error", "serverTotal": null},
    "documents": {"status": "complete", "items": [], "reason": null, "serverTotal": 0}
  }
}
```

Sections are always conditions/Condition, observations/Observation,
diagnosticReports/DiagnosticReport, documents/DocumentReference. No procedures
or serviceRequests in v1. Section status is `complete|unavailable`; items are
always an array, reason null on success or the stable reason above, serverTotal
nonnegative integer or null. A section can be complete and empty. Failures,
invalid associations, duplicates, oversize and truncation yield an unavailable
empty section without poisoning successful sections. Limit 500 root resources,
256 KiB projected Observation JSON, 192 KiB per other section, 64 KiB Patient projection; oversized whole
responses fail closed with a generic 503 error, never silently clipped content.

### Bounded server-side collection (additive v1 coverage)

Initial page size50; max10 pages, max500 encountered entries (duplicates are an
error, never deduplicated around the budget), max1MiB decoded page body and
768KiB serialized aggregate resources. Root facade/browser collections allow500;
nested arrays retain50. Observation root-plus-component fact fanout is preflighted
at1000 before projected facts allocate. Projected observations256KiB, each other
section192KiB, Patient64KiB (896KiB combined section/patient budgets),
final B2 read reply and HTTP/browser body remain below1MiB. Assistant context is
assembled separately on the server and has the independent limits above; no
previews or bindings are attached to case responses.

Collection deadline6s; every blocking HTTP phase is at most0.5s or remaining
budget, and streamed chunks/page transitions check deadline/cancellation. Existing
facade read concurrency4/deadline7s remains. B2 thread cancellation signals the
collector cooperatively; it cannot interrupt an already-blocking synchronous
phase immediately, but no subsequent page is started after the signal is seen.
Requests require identity encoding; unexpected compressed responses fail closed,
and chunks are checked without filling a larger application buffer first.
No retries, redirects, external origins or credential forwarding. Relative next
links resolve against the current request; opaque query remains intact. Scheme,
hostname, effective port and configured base-path boundary are validated BEFORE
sending; unsafe path escapes/userinfo/fragments/control characters, ambiguous
next links and cycles fail closed. Terminal valid page means complete within
budgets, not an atomic snapshot or guaranteed server order. Changed reported
totals reject conservatively; missing/estimated totals do not imply truncation.

Coverage retains `status`, `reason`, `serverTotal` and adds nullable
`receivedCount`, `encounteredCount`, `pagesFetched`. receivedCount counts admitted
validated resources; encounteredCount counts entries visited, including the
first budget-exceeding entry (501), pagesFetched counts validated Bundle pages.
Unknown counters stay null, not invented zero. Failed sections always return
items[], but retain verified counters/optional total through safe IPC metadata.
Reasons: upstream_error, auth_failed, invalid_response, unsafe_paging_link,
paging_cycle, duplicate_resource, inconsistent_total, deadline_exceeded,
resource_limit, truncated. Client also accepts the older v1 generic reason and
missing counters as null. No URLs, patient/resource IDs or source body in errors.
Frontend exposes neutral collectionCoverage on clinical/patient/workspace DTOs;
workspace failure includes coverage on the safe gateway error for later UI work.

### Explicit resource projection

Only supplied fields are emitted; absent fields stay absent. The source of
truth for the nested field allowlists is `web/projection.py`:

- All resources: resourceType, id, meta(versionId, lastUpdated, source).
- Patient: name(use, text, family, given, prefix, suffix), birthDate, gender,
  telecom(system, value, use), address(use, type, text, line, city, district,
  state, postalCode, country), active. No identifiers/national IDs.
- Condition: clinicalStatus, verificationStatus, category, severity, code,
  bodySite, subject, onsetDateTime/onsetPeriod, abatementDateTime,
  recordedDate, recorder, asserter, evidence(code, detail).
- Observation: status, category, code, subject, effectiveDateTime/effectivePeriod,
  issued, interpretation, referenceRange, dataAbsentReason, component,
  valueQuantity/CodeableConcept/String/Boolean/Integer/Range/Ratio.
  Components preserve code, interpretation, referenceRange and the same values.
- DiagnosticReport: status, category, code, subject, effectiveDateTime/Period,
  issued, result, conclusion, conclusionCode,
  presentedForm(contentType, title, creation).
- DocumentReference: status, docStatus, type, category, subject, date,
  description, author, content(attachment(contentType, title, creation), format),
  context(period).
- CodeableConcept: coding(system, version, code, display), text. Quantities:
  value, unit, system, code. Period: start/end. ReferenceRange: low/high/type/text/age.
  References: reference/display; only bounded relative references to known
  Patient/Observation/DiagnosticReport/Practitioner/Organization types survive.

Strings are bounded at 4096 characters, nested arrays at 50 elements, root
collections at500, numbers finite.
No unrestricted object spread, nested extensions, FHIR HTML narratives,
attachment data/URLs, arbitrary links or URL-following. Display strings must
be rendered as plain text, never HTML. Source URIs are metadata only, not URLs
to fetch. Source dates and version metadata are preserved literally; never
interpret meta.lastUpdated as historical local availability.

## Errors

Except for workspace's explicit coverage failure body and partial case section
failures, errors have exactly:

```json
{"version": 1, "error": {"code": "not_found", "message": "Case not found"}}
```

Stable HTTP/code pairs: 400/bad_request, 403/forbidden,
404/not_found, 405/method_not_allowed, 503/unavailable.
Parser-level rejection may use stdlib's bounded-header/request-line status
with bad_request. Messages are fixed safe text, never exception strings,
upstream narratives, credentials or stack traces.

## Auth integration (authentication lane)
The single-user development facade above stays explicit development-only and
is not exposed on preview. Authenticated preview serves the same versioned
shapes through `web/auth_bridge.py` behind `AuthHTTPRouter` with B7 identity,
`web:auth` per-request reads, human `ai.ask` gating, view-role-only assistant
bodies, stable per-user snapshot bindings, and a global single-AI gate.
