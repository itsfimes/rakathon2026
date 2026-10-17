# OpenCode AI adapter (B5, opt-in only)

Default stays mock. The OpenCode path spawns an isolated local
`opencode serve` child and talks to it over loopback HTTP with Basic auth.
Two provider kinds exist: `local` (loopback model, OS egress attestation)
and `azure` (trusted Rakathon APIM endpoint below, explicit trust consent,
host network). P2 verified bounded clinical conversion structurally (see
`P2 live verification`); model fidelity beyond the tested structural checks
is not claimed.

## Sources

- https://opencode.ai/v2/docs/api
- https://opencode.ai/v2/docs/permissions
- https://opencode.ai/v2/docs/policies
- https://opencode.ai/v2/docs/providers
- https://opencode.ai/v2/docs/config

Doc-version skew note: the installed `@opencode-ai/sdk` (v2.0.31) schema
describes `POST /session`, `POST /session/{id}/message` with
`model: {providerID, modelID}`, and `POST /session/{id}/abort`. The
installed `opencode serve` binary (v2.0.31) does NOT serve those paths
(they return 404/405 or HTML). The binary serves the `/api/...` web API
documented below. This file documents the binary, not the SDK.

## Endpoint contract (verified against pinned binary)

Verified 2026-10-16 in an isolated net namespace (no external routes)
against `opencode v2.0.31` (`opencode --version` exit 0), child
`opencode serve --hostname 127.0.0.1 --port <reserved>`, Basic
`opencode:<OPENCODE_SERVER_PASSWORD>`, local fake OpenAI-compatible
provider on loopback. Evidence: version string, per-endpoint
status codes and bodies below.

- `GET /api/session` readiness probe, Basic protected. Returns 200
  `{"data": [], "cursor": {...}}`. Wrong or missing credentials return
  401 `{"_tag": "UnauthorizedError", ...}`. `GET /api/health` is 404 and
  `GET /health` returns unauthenticated HTML, so neither is used.
- `POST /api/session` with
  `{"model": {"providerID": "<id>", "id": "<name>"},
  "permissions": [{"action": "*", "resource": "*", "effect": "deny"}]}`
  returns 200 `{"data": {"id": ..., "model": {...},
  "permissions": [...]}}`. The model key is `id`, not `model`:
  `{"providerID": ..., "model": ...}` is rejected with 400
  `Missing key at ["model"]["id"]`. `{}` and `{"title": ...}` are also
  accepted. Session ids look like `ses_<base62>` and match
  `[A-Za-z0-9_-]{1,128}`; the client rejects anything else before
  interpolating a URL.
- `POST /api/session/{id}/generate` with `{"prompt": ...}` returns 200
  `{"data": {"text": ...}}` synchronously after provider inference.
  Missing `prompt` is 400, unknown session is 404. With the fake
  provider streaming OpenAI SSE chunks ending in `finish_reason: stop`,
  generate returned 200 with the streamed text.
- `POST /api/session/{id}/interrupt?resume=false` returns 200
  `{"interrupted": bool}`. `POST .../abort` is 404 and is not used.
- `DELETE /api/session/{id}` returns 204 empty on success, 404 for an
  unknown or already deleted session.
- `GET /api/config` returns 200 with the effective document, echoing
  `providers`, `model`, derived `permissions` deny rules, and `policies`.

## Enablement (all required, fail-closed)

```sh
export RAKATHON_AI_ENABLE=1
export RAKATHON_AI_OS_EGRESS_ISOLATED=1
export RAKATHON_AI_PROVIDER=local-loopback
export RAKATHON_AI_MODEL=example-model-name
export RAKATHON_AI_BASE_URL=http://127.0.0.1:11434
uv run rakathon-backend serve --ai opencode --watchdog-interval 1.0
```

Optional: `RAKATHON_AI_BINARY` (default `opencode`),
`RAKATHON_AI_EXPECTED_VERSION` (default `2.0.31`),
`RAKATHON_AI_STARTUP_TIMEOUT`, `RAKATHON_AI_REQUEST_TIMEOUT`,
`RAKATHON_AI_API_KEY` (forwarded only when set),
`RAKATHON_AI_KILL_FILE` (refuse/trip switch).
`AI_DISABLED=1` disables without spawning. Any missing item refuses to
spawn and `serve` exits non-zero; there is no mock fallback and no direct
provider call from the backend.

`RAKATHON_AI_OS_EGRESS_ISOLATED=1` is an operator attestation, not a proof:
the backend cannot firewall the child. OS-level egress isolation
(netns, firewall, offline host) is required to prove the child cannot
reach beyond loopback; without it keep the adapter disabled.

## Provider rules (local kind)

- Base URL must be literal loopback `http://127.0.0.1:<port>` or
  `http://[::1]:<port>`. `localhost`, `0.0.0.0`, LAN, and cloud hosts are
  rejected even when opted in. Cloud providers other than the trusted
  Azure endpoint below stay rejected because end-to-end encryption for
  cloud inference is not resolved.
- Only a local OpenAI-compatible model. The backend never copies the
  user's global OpenCode providers, auth, or plugins into the child.
- Loopback HTTP is intentionally unencrypted: the child is a trusted
  local runtime on the same host, reached only via `127.0.0.1`. This is a
  local-runtime exception, not a pattern for public IP connectors.

## Trusted Azure provider (explicit exception, `RAKATHON_AI_PROVIDER_KIND=azure`)

The single trusted cloud exception is the Rakathon APIM endpoint:

- Exact base URL `https://apim-rakathon-q7146n.azure-api.net/openai/v1`
  (one optional trailing slash is normalized). Any other host, scheme,
  port, path, query, fragment, or embedded credentials is rejected, as is
  any `api-version` or `/deployments` rewrite: the provider is plain
  OpenAI-compatible `POST {baseURL}/chat/completions` via
  `npm: @ai-sdk/openai-compatible`.
- Provider id defaults to `rakathon-azure`. The canonical id `azure` is
  refused because native hooks strip the custom `api-key` header.
- Model is the deployment name from `RAKATHON_AI_MODEL`
  (for example `gpt-6-luna-dz-eu`); no `temperature`/`max_tokens`
  overrides are set, provider defaults apply.
- Auth is the custom `api-key` header interpolated from
  `RAKATHON_AI_API_KEY` inside the child only
  (`options.headers: {"api-key": "{env:RAKATHON_AI_API_KEY}"}`,
  verified resolved by the pinned binary). No `Authorization: Bearer`
  header is sent and Bearer alone is never the auth story.
- Consent is `RAKATHON_AI_ENABLE=1` plus `RAKATHON_AI_TRUST_AZURE=1`.
  The OS egress attestation is NOT required here: Azure mode runs on the
  host network by design, and runtime `deny` policies plus the minimal
  child env are controls, not a firewall guarantee. Do not claim OS
  isolation for Azure mode. The IRIS app encrypted bridge is unchanged.

```sh
export RAKATHON_AI_ENABLE=1
export RAKATHON_AI_TRUST_AZURE=1
export RAKATHON_AI_PROVIDER_KIND=azure
export RAKATHON_AI_MODEL=gpt-6-luna-dz-eu
export RAKATHON_AI_BASE_URL=https://apim-rakathon-q7146n.azure-api.net/openai/v1
uv run rakathon-backend serve --ai opencode --env-file .env --watchdog-interval 1.0
```

`.env` holds only the secret (`RAKATHON_AI_API_KEY=<key>`, mode 0600,
owner-only, not a symlink); non-secret settings come from the environment
as above (see `azure-env.example`). The file is never auto-loaded, the
key alone never enables AI, and `ai-check` reports only
`apiKeyPresent: true/false`, never the value. Missing key or consent
refuses to spawn anything.

## Operation timeouts (AI operations only)

| Layer | Bound | Scope |
| --- | --- | --- |
| OpenCode HTTP request | 180s | per generate/session call |
| B5 gateway total | 185s | cancels adapter, interrupts session, no orphan |
| B1/B5 Unix-socket servers and clients | 190s | AI path only |
| B4 `ai.complete` / `ingest` route | 200s | AI operations only |
| B4 server + CLI for AI actions | 205s | `ai.complete`, `ingest` only |

Generic health and non-AI traffic keep the 5s defaults and B4 keeps its
30s generic pending timeout. Nothing is unbounded.

## Child isolation

- Scratch dir under `/tmp/opencode`, mode 0700, with private
  `HOME/XDG_CONFIG_HOME/XDG_DATA_HOME/XDG_STATE_HOME/XDG_CACHE_HOME/TMPDIR`.
- Child env is allowlisted (`PATH`, `LANG`, scratch homes, `OPENCODE_*`
  below, optional `RAKATHON_AI_API_KEY`); `os.environ` is never copied,
  so no OTEL, proxy, or share credentials leak in.
- Both OpenCode HTTP clients (the API client and the readiness probe)
  are built with `trust_env=False`, so proxy environment variables on the
  host can neither reroute nor inspect loopback API traffic.
- `OPENCODE_CONFIG_CONTENT` carries one custom local provider
  (`npm: @ai-sdk/openai-compatible`, `options.baseURL` loopback) plus
  `model: "<provider>/<model>"`, `permission: "deny"`, and a `policies`
  deny list. Verified: the child boots with this content and
  `GET /api/config` echoes a wildcard deny permission rule plus the
  policies; unknown config keys are silently ignored (a boot with a bogus
  key still started), so deny posture rests on the echoed `permission`
  rule, not on unknown keys. No MCP servers or plugins are configured.
- `OPENCODE_DISABLE_PROJECT_CONFIG=1`, `OPENCODE_PURE=1`,
  `OPENCODE_DISABLE_DEFAULT_PLUGINS=1`,
  `OPENCODE_DISABLE_EXTERNAL_SKILLS=1`,
  `OPENCODE_DISABLE_EMBEDDED_WEB_UI=1`,
  `OPENCODE_DISABLE_LSP_DOWNLOAD=1`, `OPENCODE_DISABLE_AUTOUPDATE=1`,
  `OPENCODE_DISABLE_MODELS_FETCH=1`, `OPENCODE_DISABLE_AUTOCOMPACT=1`,
  `OPENCODE_DB=:memory:`. These are runtime controls, not an OS sandbox.
- Spawn uses `asyncio.create_subprocess_exec`, `start_new_session=True`,
  no shell, stdio detached. Shutdown is SIGTERM to the child process
  group, wait up to 5s, then SIGKILL to the group via `os.killpg` on the
  child session only. The user's own OpenCode server is never touched.

## Model output handling

- Raw document text is sent to the provider by design so the model
  can translate it; treat the Azure endpoint as trusted plaintext.
- Output must be a JSON object: either `{"bundle": <FHIR R4 transaction
  Bundle>}` validated against the shared `common/fhir.py` allowlist, or
  `{"outcome": <OperationOutcome>, "manualReview": true}`. Anything else
  (prose, fences, wrong shapes, invented resources) is refused with no repair
  and no fallback.
- Allowed clinical types: `Patient`, `ServiceRequest`, `Observation`,
  `DiagnosticReport`, `DocumentReference`, `Condition`, `Procedure`, plus
  `Provenance` only when genuinely supported. Administrative documents map to
  a single `DocumentReference` or a manual-review outcome; `Patient` and
  `ServiceRequest` are never forced.
- Completion responses require non-empty text and are labelled
  `mode: opencode`. B1 propagates the B5 mode instead of hardcoding mock.
- Requests/responses have finite timeouts and byte caps; redirects,
  non-JSON, and oversize bodies are rejected.

## Operations

```sh
uv run rakathon-backend ai-check
uv run rakathon-backend ai-check --env-file .env
uv run rakathon-backend serve --ai mock
uv run rakathon-backend serve --ai opencode --watchdog-interval 1.0
```

Optional isolated binary smoke (never runs by default, needs the pinned
binary and a net namespace with no external routes):

```sh
unshare --user --map-root-user --net bash -c \
  'python3 backend/scripts/opencode_isolated_smoke.py'
```

`ai-check` validates local config and probes `binary --version` only; it
never starts a server or calls a provider. Dropping the kill file (or
setting `AI_DISABLED=1`) while serving trips the B5 kill switch, cancels
in-flight AI calls, interrupts the session, and closes the child.

## Verification status

- `uv run pytest -W error`, `ruff check`, `ruff format --check`,
  `mypy src tests`, `compileall`, and the offline `demo` all pass.
- Binary protocol VERIFIED for shape (2026-10-16, `opencode v2.0.31`):
  version pin, authenticated readiness via `GET /api/session`, 401 on
  bad credentials, session create with `model.providerID/id` plus deny
  permissions, synchronous `generate -> {"data": {"text"}}` through a
  fake local provider, `interrupt`, `DELETE -> 204`, config deny echo.
- Azure header path VERIFIED against the pinned binary with a fake
  OpenAI-compatible provider (isolated net namespace, loopback only, no
  external routes): child config carries the exact trusted base URL with
  `options.headers {"api-key": "{env:RAKATHON_AI_API_KEY}"}` resolved
  in-child, the fake receives the literal `api-key` header with no
  `Authorization: Bearer` fallback, requests hit `/chat/completions`
  with no `/deployments` or `api-version` rewrite, Basic control auth
  still 401s on wrong passwords, and tools stay denied with only the
  Azure pid allowed.
- Live Azure inference and clinical conversion quality are unverified
  here and stay P2 work. Remaining limits: event-stream consumption and
  operator OS egress proof for the local path.

## P2 live verification (bounded, 2026-10-16)

Two `ingest-file --ai opencode` calls through the real `BackendApp` →
B5 → OpenCode → Azure path (exact trusted endpoint, deployment
`gpt-6-luna-dz-eu`, `≤180s` each, no retries, aggregates only):

- Clinical DOCX → `mode: opencode`, 14 stored resources (`Patient` 1,
  `Condition` 3, `Observation` 8, `DiagnosticReport` 2), `manualReview`
  false, `sourceHash` equal to the input SHA-256.
- Administrative DOCX → `mode: opencode`, single `DocumentReference`, no
  forced `Patient`/`ServiceRequest`, `manualReview` false.

Structural checks enforced on both outputs (shared allowlist, required
minimal fields, valid statuses, closed references, no executable URLs).
Model fidelity is not mathematically guaranteed: only the tested structural
checks plus the counts above are claimed; anything doubtful stays
`manualReview`. Offline extraction of all 17 corpus DOCX succeeds
(`scripts/verify_docx_corpus.py`, 0 failures).
