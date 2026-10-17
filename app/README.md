# Frontend package foundation

Run commands from `app/` (Node 26+, npm). This is independent of the immutable
`sample/` specimen and does not consume `vzp_data/`.

## Commands

- `npm ci` — reproduce the exact lockfile.
- `npm run dev` — `0.0.0.0:5173`, strict port, unconfigured backend by default.
- `npm run dev:mock` — explicitly opt into synthetic data on that same port.
- `npm run preview` — loopback-only `127.0.0.1:4173`, strict port.
- `npm run typecheck`, `npm run lint`, `npm test` — compiler, zero-warning lint, tests.
- `npm run build` — production build in `dist/`; unset mode means backend.
- `npm run verify:no-mocks` — inspect every `dist/` file, including hidden manifest,
  source maps and arbitrary assets, for fixture data/module entries.
- `npm run build:mock` — explicit mock build in separate `dist-mock/`.
- `npm run verify:mock` — require reachable fixture and scripted-assistant sentinels in that output.
- `npm run check` — typecheck, lint, tests, ordinary build and backend artifact check.
  Run with mode unset/backend; it intentionally fails if an environment opts into mock.

Entry: `src/main.tsx` renders `<LoginBoundary />`, which gates the app on authentication
in configured backend mode and renders `<App>` directly otherwise; `src/session.ts`
bootstraps once per page (StrictMode-safe) with `resetBootCache()` so a new login
never inherits the previous user's clinical bootstrap.

## Authentication gate (configured backend only)

With `VITE_DATA_MODE=backend` (or unset) **and** `VITE_BACKEND_API_BASE=/api/v1`, the
boundary first calls `GET /api/v1/auth/session` (same-origin cookies, no clinical
requests) and shows the Czech login form (`src/features/auth/LoginView.tsx`) while
unauthenticated. Login posts JSON `{username, password}` with `X-Rakathon-Auth: 1`;
logout posts with the in-memory `X-CSRF-Token` and clears local clinical state plus
in-flight requests **before** contacting the server. The browser never sees the
opaque session token (HttpOnly cookie) and auth secrets never touch
`localStorage`/`sessionStorage`/URLs/logs. Failures stay generic
(`invalid_credentials` → one shared message, `429` → retry-later, `5xx`/network →
unavailable) with no account enumeration, no signup, no password reset and no SSO.

A signed-in user gets an identity bar (`Přihlášeno: jméno.příjmení`, server role,
`Odhlásit`) above the existing workspace. Clinical reads go through the real
facade (`GET /api/v1/session`, typed `workspace` with coverage/pagination
counters, exact `cases/{id}` with report hierarchy); the assistant `POST`s the
exact opt-in preview with its transport binding plus the in-memory `X-CSRF-Token`
(the browser sets Origin itself, the app never forges it). Partial upstream data
stays an honest typed `unavailable` coverage envelope — never a login loop, a
fake workspace or invented counts. An HTTP `401` on any clinical read or
assistant call returns to login with an expiry notice and clears clinical state;
`403` keeps the session. The request `role` is only the UI view
(`koordinator`/`pacient`/`lekar`/`mdt`) and never a server permission; real
permissions come from the server matrix and the session capability flags. Mock
mode (`VITE_DATA_MODE=mock`) remains explicitly labeled demo and performs no
auth requests.

## Public build-time source settings

`VITE_DATA_MODE` selects the provider; `VITE_BACKEND_API_BASE` explicitly enables the read facade:

| Value | Result |
| --- | --- |
| unset (`undefined`) or exact `backend` | Unconfigured when API base is absent; no patient data or requests |
| exact `mock` | Explicit, isolated in-memory synthetic provider |
| empty string or anything else | Typed configuration error before any provider import |

There is no fallback, persistence, query parameter, role-specific source or runtime
source toggle. `.env.example` contains backend plus a commented API opt-in. No actual `.env` is shipped.
Vite settings are public build-time values: **never put credentials in `VITE_*`**.
Changing the setting requires restarting the dev server or rebuilding/redeploying;
it is not a runtime kill switch for an already delivered mock build.

`src/data/bootstrap.ts` owns the literal static mock guard and dynamic imports.
Do not statically import/re-export mock modules from any other source subtree.
The backend build eliminates that subtree; source maps are included in verification.
Do not add fixtures to `public/` or UI source. Source boundary tests include all
future `src/` modules, not just today's feature directory names.

## Stable UI contract

Call `bootstrap()` from `src/data/bootstrap.ts` once. Discriminate
`BootstrapResult.status`: `configuration-error` vs `session`. Then discriminate
`session.mode`: both have `gateway` and separate required `assistant`; mock additionally has `demoControls`.
The shell must show persistent mode/provenance, including loading/error states;
mock role switching is neither authorization nor source selection.

All domain types and `success`/`failure` helpers are exported from
`src/data/contracts.ts`. `Gateway.readWorkspace(signal?)` and
`Gateway.readCase(caseId, signal?)` return `Promise<Result<T>>`. Error codes:
`configuration-error`, `backend-unconfigured`, `unavailable`, `not-found`, `aborted`.
Unavailable is never a successful empty queue. Handle cancellation/request identity
when switching cases; do not render a previous case under a new selected name.

`Workspace` contains ISO `asOf`, nullable `defaultCaseId`, queue and provenance.
Queue/counts and MDT completeness counts are derived from arrays, not duplicated
totals. Age, diagnosis, priority, phase and `nextStep` may be null when not supplied.
`CaseDetail` contains identity, phases, shared nextStep/documents, priority narrative,
patient event/instruction/journey/coordinator, doctor source fields/referral journey/
obligations, and MDT meeting/finding/required document IDs/draft/blocked finalization.
Dates are ISO strings; format them in Czech without shifting date-only values
through timezone conversion. Static labels/icons can live in UI; person names,
clinical/source narratives, dates, owners and case values cannot.

Documents are the shared completeness/review truth. A source field references its
`documentId`; the mock adapter keeps review state synchronized. Queue and detail
share the task ID/state. After a successful local demo mutation, re-read gateway
snapshots to refresh views. There are no subscriptions or state-library contracts.
`DemoControls.acceptTask(taskId)`, `markDocumentReviewed(documentId)`, `reset()`
return `Promise<Result<void>>`. Acceptance/review are local only; reviewing a missing
document does **not** supply it or establish a diagnosis. Reset restores the seed
and does not switch source. Finalization remains blocked; no clinical send/sign/AI functions.

In explicit mock mode all six cases are selectable synthetic cases. The five additional cases use clearly
synthetic helper-generated detail (including illustrative ages); they are not medical
records. Fixture data and its reachable sentinel exist only in `src/data/mock/`.
Read snapshots are cloned and deeply frozen; nothing is persisted across sessions.

## Read-only IRIS development adapter

The exact v1 contract lives in `../backend/docs/web.md` (`HTTP edge` plus `CLI`).
Auth login/session/logout works and the authenticated clinical facade is
integrated (`GET /api/v1/session|workspace|cases` plus the capability-gated
assistant `POST`). Start the edge separately
on loopback port 8765, then:

```sh
RAKATHON_BACKEND_PROXY_KEY_FILE="$PWD/../backend/runtime/web-proxy.key" \
VITE_DATA_MODE=backend VITE_BACKEND_API_BASE=/api/v1 npm run dev -- --port 5174
```

`VITE_BACKEND_API_BASE` must equal `/api/v1`, never an arbitrary URL. The Node-only
Vite config reads the private key file outside `app/` (regular, non-symlink, owner
0600, single link; parent symlinks rejected). It overwrites the upstream key and
Host, strips rejected forwarding headers, preserves Origin and fixes the target to
`http://127.0.0.1:8765`. The key value never enters browser env/define/responses.
Absent server key setting disables the proxy. Preview remains loopback-only and
does not install a development proxy; deployment needs its own secured boundary.

Authenticated demo (explicit `demo` store, throwaway directory, never the real DB;
exact CLI shapes live in `../backend/docs/auth.md`). Run backend commands from the
authentication worktree with `uv run --project backend`:

```sh
uv run --project backend rakathon-backend auth-init --auth-store demo --auth-dir /tmp/opencode/rakathon-auth-demo
uv run --project backend rakathon-backend auth-user-add --auth-store demo --auth-dir /tmp/opencode/rakathon-auth-demo --username jana.novakova --role viewer
uv run --project backend rakathon-backend auth-serve --auth-store demo --auth-dir /tmp/opencode/rakathon-auth-demo --origin http://127.0.0.1:5173 --allow-loopback-http --bind 127.0.0.1 --port 8765 --runtime-dir /tmp/opencode/rakathon-auth-run
RAKATHON_BACKEND_PROXY_KEY_FILE=/tmp/opencode/rakathon-auth-demo/proxy.key \
VITE_DATA_MODE=backend VITE_BACKEND_API_BASE=/api/v1 npm run dev -- --host 127.0.0.1
```

The proxy key file is server-only (Vite dev proxy reads it, the browser never sees it).

The origin must match the served address exactly (`127.0.0.1`, not a `localhost`
alias). Passwords are read via `getpass` (never CLI args) and are never printed.

Role selection is presentation, not authentication. Connected data is
**not assumed synthetic**. Do not expose this
development server publicly. No DB settings/credentials belong in browser variables.

`src/data/backend/{schema,dto,gateway,projection,clinicalProjection,values}.ts` validate
bounded v1 responses, reconstruct allowlisted FHIR fields and produce detached frozen
clinical/patient DTOs. AbortSignal and exact patient/subject checks are preserved.
Workspace 503/failed coverage is unavailable, never a successful empty queue; section
failures remain independent. Lists read summaries only, without per-case fanout.
Unknown workflow/demographics stay null. Full birth dates alone establish age (including
zero), relative to fetch date. No first Condition becomes a primary cancer diagnosis.
Source issue/effective dates and exact versions remain distinct; local availability is
unknown. Missing version is explicitly `unknown`. Fetch time is only a transport time.
No MDT preparation is invented without meeting metadata, requirements and availability.
Plain text only: no FHIR HTML, attachment data/URL fetching or raw clinical data in
assistant calls.
Patient rendering consumes only its explicit PatientRecord allowlist, including narrow
section coverage. Clinical revisions are opaque local invalidation tokens.

Assistant stays unavailable unless the session reports the assistant capability;
DemoControls remain mock only. Unknown cases return not-found and failures never enable mocks. Without the API
base setting the old zero-request `backend-unconfigured` behavior remains unchanged.

## Assistant phase one: headless only, not real AI

- `src/assistant/contracts.ts`: `Assistant`, request/reply/result, role/source/field IDs,
  fixed app-owned source/field labels and `ASSISTANT_LIMITS` (1,000 input characters,
  6,000 output, 32 fields, 320 characters per field, 4,000 aggregate context characters,
  8 in-memory transcript entries). `send(request, AbortSignal)` is explicit and required.
- `src/data/backend/assistant.ts`: `UnconfiguredAssistant`, unavailable/none, zero requests.
  `BackendAssistant` posts the exact opt-in preview with its binding to the same-origin
  facade with the in-memory CSRF header; `401` ends the session, `403` keeps it.
  No SDK, URL, credentials, browser keys, hidden lookup or mock fallback.
- `src/data/mock/assistant.ts`: exact-prompt scripted demonstration, reachable only through
  the existing mock dynamic import; every reply identifies itself as scripted, not AI.
  The required artifact sentinel is an internal mock capability marker, never reply text.
- `src/assistant/prompts.ts`: `ASSISTANT_PROMPTS[role]`, exact supported prompt strings.
  Other free text gets an explicit unsupported reply, not a clinical keyword heuristic.
- `src/assistant/context.ts`: `buildAssistantContext(view, detailOrNull, fresh)` returns
  an immutable minimal `{role, fields}` or null. Oversize projection fails closed, not
  silently truncated. No identity/age/diagnosis/full case/excerpts/history/local identifier
  fields are selected. Coordinator and MDT document entries use fixed app-owned labels
  mapped from document `kind` and `state` enums only; document labels/state labels and all
  source metadata (including titles/dates/pages) are omitted. Existing field/source IDs
  stay unchanged, and preview remains the exact payload. Other supplied free text, such
  as task titles and patient instructions, still requires upstream minimization.
- `src/assistant/useAssistant.ts`: `useAssistant(options)` returns `input`, `messages`,
  `pending`, fixed safe `error`, `available`, `provenance`, `contextAvailable`,
  `contextPreview`, `selectedContext`, `contextSelected`, and actions `setInput`,
  `selectContext`, `send`, `stop`, `clear`, `close`. No persistence/logging/automatic sends.

### Exact designer wiring recipe (UI deliberately deferred)

1. Own `open` in the shell; call the hook unconditionally with current `session`, `view`,
   selected `caseId`, demo mutation `version`, `open`, and an optional numeric `resetKey`
   if reset must clear immediately before a mutation completes. A version change already
   clears/aborts. Session identity must be stable, not a fresh object every render.
2. From `useCaseDetail`, derive `fresh = detail.status === 'ready' && detail.fresh`.
   Pass the same `fresh` to `buildAssistantContext(view, readyDetailOrNull, fresh)` AND
   hook `contextFresh`. Use the same selected case ID and version as that resource;
   never substitute queue data or another case's ready value. `ResourceState.ready.fresh`
   is false while the previous same-case snapshot remains on screen during refresh.
   Stale snapshots cannot be reselected; failed refresh remains unavailable. Do not infer
   freshness from `status === 'ready'` alone.
3. `contextSelected` starts false. Render `contextPreview.fields` **exactly** using
   `ASSISTANT_FIELD_LABELS[field.key]` and `field.value` as plain text. This is the entire
   context payload, with typed `source` IDs and role; do not add other fields to request
   or preview. Checkbox calls `selectContext(checked)`, disabled unless `contextAvailable`.
   A local selected-case label may be displayed after opt-in but is not transmitted.
4. Explicit form submit calls `send()`; suggested prompt action calls `send(prompt)`
   (or sets input for user review). Input `maxLength=ASSISTANT_LIMITS.input`; only one
   pending send is allowed. Nothing sends on opening, typing, selecting context or refresh.
   History is display-only and never transmitted. `stop()` aborts safely without erasing
   visible history; `clear()` clears input/history/context and aborts. Limit reached means
   clear before another send, never silent history truncation.
5. Close/Escape/native-dialog cancel calls `close()` AND sets `open=false`. Case/view/
   version/session/reset/freshness changes and unmount abort pending work and clear state;
   late replies are discarded even when transport ignores abort. Controlled closing alone
   also clears state. Native modal focus/inertness/focus return and navigation-close-before-
   focus remain the designer's responsibility. No UI/CSS changes are included here.
6. Render user text and `message.reply.text` as plain text only. Each reply carries
   `reply.provenance`; keep scripted vs real/unavailable visible. Sources are only
   `reply.sources` mapped through `ASSISTANT_SOURCE_LABELS`, with no arbitrary hrefs,
   selectors, evidence-approval claims or tool actions. No navigation targets are promised.
   Keep source-mode strip/provenance visible in the modal too.

For a future real adapter, supply a vendor-neutral authenticated same-origin server
contract first, implement the capability with `availability: 'available', provenance:
'server'`, validate bounded schemas, normalize failures and honor AbortSignal. Backend
authorization, minimization, retention, rate limits, evaluation and governance approval
are prerequisites; browser role and opt-in are not authorization or legal consent. Never
send hidden case/history enrichment. Structural allowlists cannot detect names/PHI inside
otherwise approved free-text fields; upstream text needs its own minimization policy.
No real AI is currently implemented. Research/limits: `../assistant-research.md`.

## UI structure (React)

- `src/styles/` — `index.css` declares layers `tokens → base → components → layout → theme`.
  `tokens.css` holds every customisable value (colours, type, spacing, borders, radii, shadow,
  targets, motion, icon sizes/strokes, component sizes). Override in `theme.css`. Breakpoints
  (1100 / 760 / 380px) are static in `layout.css` because CSS variables cannot drive media queries.
  Typography is set by semantic roles: `--type-page-title`, `--type-panel-title`, `--type-task`,
  `--type-label`, `--type-body`, `--type-patient`, `--type-data`, `--type-meta` (+ `--lh-data`,
  `--lh-quote`, `--lh-control`, `--control-pad-y`, `--wrap-prose`). Example theme override:
  `@layer theme { :root { --c-accent: #0B6E4F; --type-panel-title: var(--fs-md); } }` in `theme.css`.
- `src/icons/` — authored SVG paths, `IconSprite`, `Icon`.
- `src/components/ui/` — primitives, one per file: Panel, Button, Tag, Notice, Disclosure, Facts,
  StepBar (+MiniSteps), NextStep, Checklist, Cells, Timeline, CalendarTile, Table/StackCell,
  Field/Input/Select, Segmented (links/radios), Skeleton, Avatar.
- `src/components/shell/` — ModeStrip (persistent data-source strip), AppBar, ViewHead,
  DataState (loading/error/empty), CaseGate, AboutFooter.
- `src/features/{coordinator,patient,doctor,mdt,specimen}` — role compositions and their panels;
  `features/shared` holds cross-role task/document pieces. Specimen is a design tool, not a role,
  and contains no case data.
- `src/hooks/` — `useView` (hash/`?role` allowlist + history), `useResource`/`useCaseData`
  (AbortController + request identity), `useDemoActions` (mock-only local changes, re-read after
  success), `useStickyOffsets` (measured strip/app-bar heights → scroll offsets).
- `src/lib/` — Czech date formatters (no timezone shift), status labels, role list.

Behaviour: mock mode shows `DEMO · SYNTETICKÁ DATA · bez backendu` pinned on every screen with
“Obnovit demo”; backend mode shows its unconfigured/connected/unavailable state truthfully,
including in the assistant. Missing data is unavailable, never a fallback or fake empty queue.
Local actions are labelled “(lokálně v demu)”; urge/inform/
confirm-extract buttons are disabled; finalisation is always disabled.

Separate explicit demo: `npm run dev:mock -- --port 5175` (no backend key needed).
Configured development: port5174 command above; default port5173 stays unconfigured.
