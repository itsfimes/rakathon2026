# Auth contract (Phase A, offline core)

## Scope
Replaceable authentication block B7 plus persistent demo store under B2.
B7 authenticates identity. B6 authorizes actions. No public signup over HTTP.
Provision and disable are owner-local CLI administration operations only.
Phase A is in-process synchronous calls. No new B2 UDS recursion in Phase A.

## Public API
```
AuthService(store, keys, provider, clock=system_clock, audit=None)
login(username, password) -> LoginResult(session_token, identity)
resolve(session_token) -> UserIdentity(user_id, username, role, auth_version)
logout(session_token) -> None (idempotent)
csrf_token(session_token) -> str (HMAC with separate CSRF key)
provision_user(username, password, role) -> UserIdentity
disable_user(user_id) -> None
set_role(user_id, role) -> None
set_password(user_id, password) -> None
role_for_user(user_id) -> str | None (safe, server-authoritative)
AuthBlock = AuthService
LocalPasswordProvider(time_cost=3, memory_cost=65536, parallelism=1)
```
Constructors accept an injectable `PersistentAuthStore`, `KeySet`, clock, and audit callback.
`role_for_user` returns one of admin/coordinator/clinician/viewer or None.
It never returns watchdog to human callers. Watchdog stays service-only.

## Identity rules
Username is `name.surname` after NFKC plus casefold, max 96 chars.
Each part is nonempty unicode letters with optional internal single hyphens.
Exactly one dot. No whitespace, control chars, or slashes.
Password is 15-128 unicode chars and at most 1024 UTF-8 bytes, used verbatim.
Roles are admin, coordinator, clinician, viewer. No human watchdog accounts.

## Secrets
Three independent 32-byte keys live in a private JSON key file.
File creation uses O_CREAT|O_EXCL|O_NOFOLLOW mode 0600 and never overwrites.
Load requires a nonsymlink regular file owned by the caller at 0600, size-capped.
The parent directory must be private (no group/other bits) and owned by the caller.
The proxy key loader additionally requires a private nonsymlink parent and
reads through O_NOFOLLOW plus fstat, so symlinks and parent swaps fail closed.
Blind username index is HMAC-SHA256 with the index key. The DB has no plaintext names.
Profiles use AES-256-GCM with a random 12-byte nonce. AAD binds user id and schema v1.
Session tokens are `secrets.token_urlsafe(32)`. Only the SHA-256 hash is stored.
CSRF values are HMAC-SHA256 of the token with the separate CSRF key.
Argon2id defaults are t=3 m=65536 p=1. Malformed stored params are clamped.
Unknown or disabled users still run a dummy verify and return invalid credentials.

## Sessions
Absolute lifetime is 8 hours. Idle timeout is 15 minutes.
Expiry, revocation, account disable, and auth version or role mismatch invalidate.
Last-seen updates use conditional UPDATE compare-and-swap on prior last-seen.
A CAS loser rereads and revalidates (expiry, idle, account active, auth
version, role) up to 3 times: it accepts when last-seen already advanced past
its own timestamp and retries CAS otherwise. Deleted or revoked sessions never
resurrect and last-seen never moves backwards.
At most 32 sessions per user with bounded pruning of oldest entries.
IRIS pruning deletes only rows whose last-seen still matches the prune
snapshot, so a concurrently refreshed session survives.

## Rate limits
Persistent per-account and global attempt counters in the same store transaction.
Defaults are 10 per account per minute and 100 global per minute.
Reservation happens before expensive verification, including unknown users and
malformed usernames (mapped to a separate HMAC domain, still generic 401).
Rate state uses fixed slots keyed by UNIQUE (scope, key, slot) with ts plus an opaque
reservation id. Each slot holds one attempt until ts <= now - window. Allocation is a
single conditional UPDATE (ts, reservation id where ts <= cutoff wins the slot); when the
row is absent a single INSERT creates it and the UNIQUE constraint decides races. No
read-then-COUNT gate exists. Probing is bounded by the limit plus a small serialization
retry. A denied global reservation releases only its own account slot by reservation id,
never sibling rows at the same ts. A crash between the two reservations may leave one
account slot consumed until its TTL expires: conservative fail-closed, never a global
cap bypass. The single conditional write plus UNIQUE guard is READ-COMMITTED safe
independent of transaction read isolation. Scope cutoffs stay separate so future window
tuning cannot cross-prune. Transient store errors retry at most 3 times.
There is no permanent lockout.
Bounded concurrent hashing uses a nonblocking semaphore. Overflow is rate limited.
IRIS SQL is exercised with offline SQLite-backed fakes only; no live IRIS SQL proof
exists and none is claimed. The fakes assert the UNIQUE slot guard and schema indexes,
including shared-DB multi-instance caps without a writer lock.

## Stores
Typed storage port is `PersistentAuthStore`. It exposes narrow named operations only.
SQLite demo store is explicit persistent stdlib sqlite3 with journal mode DELETE.
The DB file is private 0600 with owner and symlink checks and safe parent checks.
IRIS store uses the existing `IrisSqlConfig` plus an injectable factory.
It uses the shared task_sql connector style with bound parameters and commit/rollback.
Missing driver, key, or config fails closed with store unavailable. No fallback.
`init_schema` must be called explicitly. DDL never runs implicitly at startup.
Timestamps are numeric UTC epoch seconds.

## Errors and audit
Authentication failure and store unavailability are distinct safe errors.
Messages never include username, password, token, hash, or profile material.
Repr of records, results, and services redacts secrets.
Audit callback receives only opaque user id, event type, and status.
There are no default accounts and no hardcoded passwords.

## Phase B boundary
Phase B adds a real B7 auth/session UDS request/response connector.
Trusted path becomes web:auth to B4 source with no Envelope change.
B6 remains the server-authoritative role resolver.
HTTP auth endpoints are `/api/v1/auth/login|logout|session`.
They are distinct from the existing clinical `/api/v1/session`.
Production uses `__Host-` cookie with Path=/. Loopback uses an explicit different name.

## Limitations
Demo SQLite store is selected explicitly by the operator.
IRIS SQL driver is absent offline, so the IRIS adapter is verified fail-closed only.
Key rotation needs a migration and is out of scope for version one.
No HTTP, cookie, UDS wiring, or frontend is added in Phase A.

## Phase B (implemented, offline)

## B7 UDS connector
`b7/handler.py` exposes `auth.login`, `auth.resolve`, `auth.logout` on target `b7`.
Only source `web:auth` is accepted. All three use `DataKind.PROPRIETARY`.
Health stays server-level `METADATA`. Payloads are closed shapes with bounded strings.
Every operation runs in `asyncio.to_thread` so Argon2 never blocks the event loop.
Login replies carry the session token plus derived CSRF inside proprietary IPC only.
The token never appears in Envelope routing fields, health, logs, or client config.
`BackendApp(auth=bundle)` registers the `b7` server. Default apps stay six-service.

## HTTP to B7 wire (final connector)
`auth-serve` keeps constructing `AuthService` only for the B7 backend plus the
trusted B6 role resolver. HTTP router callbacks use nothing but
`B7SocketClient(runtime_dir, tokens["web:auth"])` through the typed
`build_login_callables(port: AuthSessionPort)` adapter, so the local sync
service object is never invoked from HTTP even while alive. Removing the B7
listener, a wrong registry token, or a missing socket maps to 503
`not_configured` on login, session, and logout alike.
`b7/client.py` exposes `AuthenticationPort` (alias `AuthSessionPort`) with
`login(username, password) -> LoginResult`, `resolve(token) -> UserIdentity`,
`csrf_token(token) -> str`, and `logout(token) -> None`, plus `B7SocketClient`
with the same sync shape over `auth.login|resolve|logout` proprietary
envelopes from source `web:auth`. Replies are verified by expected source,
action, proprietary kind, closed payload shape, bounded strings, positive
integer `authVersion` (booleans rejected), and contract role allowlist; body
`userId` and role are never trusted for decisions. `csrf_token` replays
`auth.resolve`, which already returns identity plus CSRF, so no token-keyed
CSRF cache exists. Error mapping is strictly by code: `invalid_credentials`
becomes `AuthFailed` (401), `rate_limited` becomes `RateLimited` (429), and
every other wire, socket, timeout, source, kind, or shape failure becomes
`StoreUnavailable` (503). Unknown protocol errors never become 401, and raised
errors plus `repr` carry no remote body, username, password, or token. The
client runs one `asyncio.run` RPC per call with a finite 5 second default
(capped at 30 seconds) and must be called from HTTP worker threads only, never
from the B7 event-loop thread. A minimal B7 socket server implementing the same
wire answers HTTP with no HTTP or core changes, which is the
provider-replaceability proof. B7 still delegates to the typed
`PersistentAuthStore` port in-process; there is no new SQL socket and no
sensitive payload metadata. Role lookup backing stays the local
`LocalPasswordProvider` deployment, so a future SSO adapter will need an
explicit role-provisioning policy; no SSO is implemented or claimed. Shutdown
drains blocking HTTP worker shutdown and join in `asyncio.to_thread` so the B7
loop can finish in-flight calls before `app.close()`, with a finite 10 second
join bound and socket removal.

## B4 typed action client
The `make_b4_dispatch` stub is removed; it ignored method and body and always
probed `tasks.read`. `web/edge.py` now exposes `B4ActionClient` with
`call(verified_identity, action, payload) -> Envelope` plus
`make_b4_action_client(runtime_dir, token, timeout=5.0)`. The exact requested
`USER_ACTIONS` entry travels through the existing `web_envelope` helper with
`request_kind(action)`, so caller authority fields stay rejected, the verified
identity is server-resolved only, and auth, token, source, and correlation are
checked by the UDS layer. No API path maps to an action and no hidden probe
runs. `AuthMiddleware.protect` remains the only composition callback; the
former default clinical 503 is superseded by the merged AuthBridge facade
(see Merge integration below), and unauthenticated clinical traffic stays
401-first with no B4 network call.

## Trusted web identity
`web:auth` tokens are minted only by `fresh_tokens_with_auth` and live server-side.
`B4Router(web_sources=frozenset({"web:auth"}))` is default-deny without that source.
`_handle_web` accepts only a nonempty `user_id` resolved by the edge through B7.
Legacy `frontend:<user>` keeps its exact claimed==expected check via shared
`_authorize_and_route`. `web_envelope()` builds B4 envelopes from verified identity
and rejects `userId`, `user_id`, `role`, `username` keys in caller payloads.

## B6 dynamic roles
`check` and `make_authorize_handler` accept optional `role_resolver(uid)->role|None`.
`None`, unknown roles, resolver exceptions, and human `watchdog` mappings all deny.
The auth runtime injects `AuthService.role_for_user`, so disable, role change,
and auth-version bumps revoke immediately. `B2Service` and `B4Router` accept
optional `is_privileged(uid)->bool` for admin/coordinator/watchdog queues.
Exceptions fail closed. Without callbacks the static sets apply unchanged.

## HTTP edge
`web/router.py` holds framework-neutral `AuthHTTPRouter`. `web/edge.py` holds
`AuthMiddleware.protect(next_handler)`, typed `build_login_callables`, and the
honest `B4ActionClient` plus `make_b4_action_client` (the old
`make_b4_dispatch` stub that always probed `tasks.read` is removed).
`web/server.py` is a stdlib `ThreadingHTTPServer` bound to loopback only.
`POST /api/v1/auth/login` needs proxy key, exact Origin, JSON, and
`X-Rakathon-Auth: 1`. `GET /api/v1/auth/session` needs no CSRF.
`POST /api/v1/auth/logout` is idempotent 204 with cookie clearing on success.
A store outage during active logout returns 503 without clearing the cookie so the
client keeps hiding data, warns, and retries; expired or revoked tokens clear
idempotently without requiring re-revocation.
Bad credentials map to generic 401 `invalid_credentials`, including malformed
usernames at this layer (provisioning stays strict), limits to 429
with `Retry-After`, missing backends to 503. Error bodies never carry names,
hashes, tokens, or request bodies. Authenticated clinical traffic is served
by the merged AuthBridge facade (see Merge integration below).
Unauthenticated
clinical traffic is denied 401 before any routing or downstream call.
Writes need exact `X-CSRF-Token` plus Origin. `GET /health` is proxy-gated
liveness with no identity or database claims. Body cap is 16 KiB with strict
header, path, timeout, and duplicate-header rejection. Request lines and
bodies are never logged. Production cookie is `__Host-rakathon_session`
with Secure. Explicit `--allow-loopback-http` with a loopback Origin uses
the different `rakathon_session_loopback` cookie without Secure.

## CLI
`auth-init --auth-store demo|iris --auth-dir PATH` creates a private 0700
directory with `auth.authkey`, `proxy.key` (0600), and the demo DB schema.
It refuses existing paths and never overwrites secrets. Use a throwaway directory
such as `/tmp/opencode/rakathon-auth-demo` for local provisioning so secrets stay
git-ignored. `backend/runtime/` in this repo is a git-ignored anchor only, not a real
or root `/runtime` directory.
`auth-user-add --auth-store ... --auth-dir ... --username name.surname --role R`
reads the password twice via getpass and provisions exactly one account.
`auth-user-disable --auth-store ... --auth-dir ... --user-id UID` revokes
sessions immediately. `auth-serve --auth-store ... --auth-dir ... --origin URL
--allow-loopback-http --bind 127.0.0.1 --port 8765 --storage mock|iris-fhir
--runtime-dir PATH` serves UDS plus the HTTP edge. `--auth-store` is required
with no fallback. IRIS SQL credentials come from process environment only;
the `--env-file` whitelist stays closed. Missing keys, schema, or providers
fail closed with no seeding. Shutdown closes HTTP workers and all sockets.

## Demo
Run from the authentication worktree with `uv run --project backend`:
```
uv run --project backend rakathon-backend auth-init --auth-store demo --auth-dir /tmp/opencode/rakathon-auth-demo
uv run --project backend rakathon-backend auth-user-add --auth-store demo --auth-dir /tmp/opencode/rakathon-auth-demo --username jane.doe --role viewer
uv run --project backend rakathon-backend auth-serve --auth-store demo --auth-dir /tmp/opencode/rakathon-auth-demo --origin http://127.0.0.1:5173 --allow-loopback-http --bind 127.0.0.1 --port 8765 --runtime-dir /tmp/opencode/rakathon-auth-run
```
Login with `X-Rakathon-Proxy-Key: <proxy.key contents>` from `proxy.key`,
exact `Origin`, and `X-Rakathon-Auth: 1`. The proxy key never ships to browsers.

## Phase B limits
Auth-only demo. Protected clinical routes are now served through the merged
AuthBridge facade (see Merge integration below); the prior 503-until-facade
note is superseded.
No OIDC flow is claimed. No browser credential storage is used.
Upstream Host must exactly match the configured listener authority (set from
the server builder) or an explicit allowlist entry; wrong ports and aliases
are rejected and duplicate Host headers are refused. Origin stays the exact
configured value and is independent of Host by design.
`b6 authorize` binds payload `userId` to envelope `userId`: both must be
nonempty and equal before any role check. Mismatch or missing identity is
denied. Health stays a separate server-level check.
Watchdog is intentionally inert: `auth-serve` runs with `watchdog_interval=None`
and the B3 loop cannot be enabled until a service policy exists. There are no
human watchdog accounts and no static fallback privilege. This is a documented
limit, not a full service refactor.
No MFA or SSO is implemented and none is claimed for production.
No hospital production readiness is claimed. The only credential provider is
`LocalPasswordProvider`; the replaceable port is implemented, but a real directory
or SSO provider implementation remains future work. No fake SSO is included.
Loopback binding is a development posture only: production must terminate TLS
at a front proxy and forward to the loopback listener with the exact Origin
and proxy key intact. No remote auth HTTP egress is approved or implemented;
the B7 and B4 UDS paths accept local runtime directories only and reject URL
or HTTP remotes. The root E2EE line is unchanged by this lane.
Frontend login/session wiring is COMPLETE per the reconciled frontend report
(app code untouched by this lane; app README docs only). Connector proof is
532 backend pytest PASS with `-W error` (513 prior plus 19 new connector tests:
5 HTTP-to-B7 flow, 8 wire negatives plus fake-provider exchange plus SIGTERM
shutdown, 6 B4 action-client), ruff check plus format clean, mypy
`src tests scripts` clean for 156 files, compileall clean, demo clean.
All five final closure reviews PASS: comments, zero-warning toolchain, imports,
file size, and correctness/security. The parent also freshly ran frontend
`npm run check`: 363 tests, types, zero-warning lint, production build, and
seven-file mock-exclusion verification PASS.
Known limits: no live IRIS proof (offline fakes only), demo SQLite needs a fresh
`auth-init` after the slot-schema change (no auto-migration of live agent DBs), and a
crash between account and global reservations may hold one account slot until its TTL.

## Merge integration (authentication lane)
Clinical API is integrated behind `AuthHTTPRouter` via `web/auth_bridge.py`.
`GET /api/v1/session|workspace|cases/{id}` and `POST /api/v1/assistant` map
to the versioned `WebService` shapes with sanitized `WebError` mapping and
404/405 defaults; no fake 200/503. Reads use per-request identity-bound
`web:auth` envelopes with opaque B7 user IDs, never shared `viewer`.
`POST /api/v1/assistant` accepts the UI view `role` (`koordinator|pacient|
lekar|mdt`) only on that route; `userId`, `user_id`, `username` stay rejected
and identity comes from B7 alone. Human `ai.ask` is authorized per verified
user via `web:auth` before any AI; coordinator, clinician and viewer human
roles can ask in all four UI views. `web-assistant` keeps
the literal service-principal `ai.complete` path with B4/IPC clamps.
Assistant requests are `{role,text,caseId?}`. A supplied case triggers the full
record read under the human identity before Azure egress; no case means general chat.
No snapshot bindings remain. The global single-AI gate still returns429 when busy.
`auth-serve` defaults to mock AI off; `--assistant` plus provider env, auth
scheme, timeout<=60, consent, and kill gates enable direct mode only.
Live IRIS is not verified in this lane; no MFA/SSO or production claims.
Backend gates: 783 pytest PASS with `-W error`, ruff clean, mypy clean.
Final designer plus closure reviews are PENDING on the merged state.
