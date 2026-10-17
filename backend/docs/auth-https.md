# IRIS-only HTTPS authentication storage (local implementation; NOT DEPLOYED)

This backend option is `--auth-store iris-https`. It uses a private typed API,
**not** Atelier SQL at runtime, native SQL, FHIR resources, or a database fallback.
Clinical storage must separately be selected as `--storage iris-fhir`. Existing
`iris` (native SQL) and `demo` options are unchanged; neither is selected implicitly.

## Status and release gates

Python tests use synthetic records and `httpx.MockTransport`. Static source checks
are **not** evidence of ObjectScript compilation, SQL execution, authorization,
rollback, duplicate-key parsing, transaction isolation or concurrent rate limiting
on IRIS. All seven classes under `iris/auth/` must pass independent source review,
compile on the owner's IRIS 2026.1, and pass the live synthetic-only checks below
before enabling a Web Gateway application or switching the running backend.
No remote changes, local keys, accounts, or service restarts accompany this change.

## Server-only configuration

In an owner-only, nonsymlink `0600` env file (not Git, not any `VITE_*` setting):

```dotenv
RAKATHON_AUTH_HTTPS_URL=https://iris.racek.xyz/auth-storage/v1/operation
RAKATHON_AUTH_HTTPS_NAMESPACE=USER
RAKATHON_AUTH_HTTPS_CREDENTIALS=fhir
```

`fhir` explicitly opts into reuse of the existing approved
`RAKATHON_IRIS_FHIR_USER` / `RAKATHON_IRIS_FHIR_PASSWORD`, and requires the configured
FHIR base to be `https://iris.racek.xyz/fhir/r4`. There is **no** automatic credential
reuse. Alternatively explicitly select `dedicated` and supply
`RAKATHON_AUTH_HTTPS_USER` / `RAKATHON_AUTH_HTTPS_PASSWORD` privately. The namespace
must be `USER`; it is server deployment configuration, not request data. Missing
selection, URL or credentials fails closed. Only the exact HTTPS URL above is
allowed; TLS certificate checks are mandatory, redirects/proxies are disabled.
The explicit loopback HTTP constructor flag exists for synthetic tests only; the
environment loader cannot enable it. Existing SQL loopback restrictions remain.

Runtime POST bodies and responses are limited to 16 KiB, with 5-second connect,
12-second I/O and checked 12-second elapsed deadline. No mutation is retried after
an ambiguous timeout. A single synchronous read cannot be preempted at the elapsed
deadline, so a chunk started before that deadline may finish up to one I/O timeout
later. Compressed responses are rejected. Remote error text is never surfaced.

## Closed wire contract

Only `POST /auth-storage/v1/operation`, JSON, authenticated as the configured
**service** account. The account is not a human web user's identity. Payload:
`{"v":1,"op":"get_user_by_id","args":{"user_id":"<32 lowercase hex>"}}`.
Responses are exactly `{"v":1,"ok":true,"result":...}` or
`{"v":1,"ok":false,"error":"bad_payload|duplicate_id|rate_limited|store_unavailable"}`.
No SQL, class, namespace, table, arbitrary role resolver or administrative method
is exposed. `init_schema()` fails locally with `administrative_install_required`.

| Operation | Exact args | Result |
|---|---|---|
| create_user / update_user | record (all UserRecord fields) | null |
| get_user_by_id | user_id | user record or null |
| get_user_by_index | username_index | user record or null |
| create_session | record (all SessionRecord fields) | null |
| get_session | token_hash | session record or null |
| cas_last_seen | token_hash, old, new | boolean |
| delete_session | token_hash | null |
| count_user_sessions | user_id | nonnegative integer |
| prune_user_sessions | user_id, keep | null |
| revoke_user_sessions | user_id | null |
| prune_expired_sessions | now, limit | null |
| rate_reserve | account_key, now, account_limit, account_window, global_limit, global_window | null |

Unknown/extra/missing fields are rejected. Booleans are not integers. IDs are 32
lowercase hex; indexes/token hashes/account keys are 64 lowercase hex. Roles are
admin/coordinator/clinician/viewer. Versions are 1..2147483647; times 0..253402300799;
keep 0..32; prune limit 1..1000; rate limits 1..10000, windows 1..86400 seconds.
Encrypted nonces are 12 bytes; ciphertext 17..768 bytes, both canonical base64.
Hashes remain Argon2id; profiles stay encrypted; session tokens remain hashed.
The bounded recursive ObjectScript scanner decodes JSON keys before uniqueness
comparison, rejecting duplicate and escape-equivalent keys before `%FromJSON`.
Its actual IRIS behavior is a mandatory live gate, not inferred from Python JSON.

Each request uses a finite two-second named service lock and one server-side
transaction. Prepared SQL has fixed internal table/column choices and bound values.
Unique collision `-119` is expected only in create-user and rate-slot claims.
Version-advancing user updates atomically revoke all sessions. Older versions and
older update timestamps fail; same-version rehash can change only hash/timestamp.
CAS and pruning use last-seen predicates. Session creation checks active identity,
role/version and the 32-session ceiling inside the transaction. Global rate denial
rolls back the account reservation too. The lock serializes this API's requests;
all writers must use this service (no concurrent legacy/native writer deployment).
Large/custom rate limits and slow SQL require server-side resource/deadline review
before release: client timeouts do not cancel a running IRIS transaction.

## Administrator installation — STOP until gates approved

There is deliberately **no** upload, compiler, application-registration or schema
installer in the Python client. GET-before-PUT is not an atomic no-overwrite guard.
Atelier source upload/compile support does not establish safe conditional creation
or permission. An administrator must verify an exclusive, non-overwriting import
procedure first. Never import over any existing `Rakathon.Auth.*` class. Stop on
an existing object, ownership uncertainty, incompatible schema or partial install.
Do not assume rollback of SQL DDL; record newly created owned artifacts separately.

After approval, an administrator in **USER** can install reviewed classes and run
`iris/auth/schema.sql` through the separately approved administrative procedure.
The DDL contains only CREATE, no DROP/replace/IF-NOT-EXISTS. Existing objects must
not be altered or removed, even if a failed installation is partially complete.
There is no exposed schema-init operation.

Portal registration must be verified by the administrator; no unverified HTTP
management route or guessed numeric authentication mask is prescribed:

- Dedicated `/auth-storage` application, namespace USER, dispatch class
  `Rakathon.Auth.Service`, password authentication only, no unauthenticated access,
  no CORS, no browser session dependency, HTTPS Web Gateway route only.
- The application definition's **Resource** property must name the narrow resource;
  an empty Resource is unsafe/public. Use the actual Portal labels for server
  2026.1; do not infer a password-authentication bitmask from newer documentation.
- Create a narrow `RakathonAuthService` resource and grant only its Use permission
  to the selected service identity plus minimum SQL/table/database permissions.
  Do **not** grant `%All` or inherit privileges into anonymous requests.
- Deliberately configure `^RakathonAuthConfig("serviceUser")` to that service
  username and `^RakathonAuthConfig("enabled")=1` only after tests. Missing config,
  wrong namespace, different principal or missing resource permission denies access.
  Restrict write access to this configuration global and the service's database
  resources. The endpoint does not accept a caller-supplied identity as authority.
- Enforce request-body, worker/time/resource limits at the Gateway and IRIS too;
  proxying the same port does not prove resource authentication is configured.

Live synthetic-only acceptance: anonymous/wrong-resource/other-account rejection;
all closed shapes and malformed/duplicate escaped keys; every operation; SQL errors
and rollback; version advancement plus stale rehash races; session insertion racing
disable; CAS loser; concurrent slot claims/unique collisions; global denial must
leave no account reservation; bounded pruning preserves refreshed rows; no secret
response/logging. These are blocked until controlled deployment is approved.

## Subsequent local activation (not performed)

Only after approved server installation and existing-table ownership verification:

1. `auth-init --auth-store iris-https --auth-dir <new-private-dir> --env-file <0600-file>`
   validates config and creates **only keys**, never a local DB or remote schema.
   It refuses an existing directory. Existing users require their original keys;
   do not replace those keys or run auth-init against existing encrypted records.
2. Provision only an owner-approved username/role using `auth-user-add` with the
   same explicit store/dir/env flags; password is privately entered, never argv.
3. Launch with `auth-serve --auth-store iris-https --auth-dir <private-dir>
   --storage iris-fhir --runtime-dir <owned-auth-runtime>
   --origin http://localhost:5174 --allow-loopback-http --bind 127.0.0.1
   --port 8765 --env-file <0600-file>`. Options follow the subcommand.
4. Vite's server-only `RAKATHON_BACKEND_PROXY_KEY_FILE` points to
   `<private-dir>/proxy.key`. Do not expose its value to the browser.
5. Verify anonymous session and protected 401, then owner login, real clinical read
   coverage and logout. No synthetic session minting or LoginBoundary bypass.
