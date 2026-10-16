# IRIS adapters (trusted bridge side only)

These adapters run inside the encrypted bridge process on trusted hospital
loopback. They are never used by the B2 client directly. B2 only sees the
`Storage` interface through ciphertext. Live integration against a real
IRIS instance is NOT VERIFIED; everything below is proven with offline
fakes and loopback tests.

Official sources:

- FHIR interactions:
  `https://docs.intersystems.com/irisforhealthlatest/csp/docbook/DocBook.UI.Page.cls?KEY=HXFHIRSTD_interactions`
- FHIR SQL builder / SDA-FHIR projection background:
  search `HXFHIRFSB_intro` in the InterSystems documentation set
- SQL vector search:
  search `GSQL_vecsearch` for `VECTOR_COSINE` and `TO_VECTOR`
- Python DBAPI:
  search `BPYDBAPI_refapi` for `iris.dbapi` connection semantics
- Target bars used during design: IRIS 2026.1, FHIR R4 4.0.1. No recorded
  patient data exists in this repository.

## Layout

- `b2/iris/config.py` reads FHIR, SQL, and vector settings from env.
- `b2/iris/fhir.py` (`DirectFhirAdapter`) talks FHIR REST over HTTPS.
- `b2/iris/sql.py` (`IrisSqlStore`) owns task tables and vector queries.
- `b2/iris/storage.py` (`CompositeIrisStorage`) composes both behind the
  synchronous `Storage` protocol used by `B2Service`.

## FHIR adapter

Configuration (placeholders, never real secrets):

```sh
RAKATHON_IRIS_FHIR_BASE_URL=https://iris-hospital.example/fhir/r4
RAKATHON_IRIS_FHIR_USER=FHIR_USER_PLACEHOLDER
RAKATHON_IRIS_FHIR_PASSWORD=changeme
RAKATHON_IRIS_FHIR_VERIFY_TLS=1
```

Rules: fixed configured base URL, HTTP Basic credentials from env only,
TLS verification on whenever HTTPS is used, `trust_env` off, redirects off,
finite timeouts, and a
1 MiB body cap. The decrypted FHIR destination is restricted to a literal
loopback address (direct IRIS web port on the same trusted host, for
example `http://127.0.0.1:<iris-web-port>/fhir/r4` bridge-side); no public
nginx endpoint ever carries decrypted traffic, so the outer B2-to-bridge
hop stays HTTPS while the final hop stays inside loopback. Plain HTTP is
accepted only for a loopback base URL with an explicit port and only when
the bridge operator enables the insecure-loopback flag; any other
non-HTTPS base is refused, and TLS verification is never disabled to make
a remote endpoint pass. Requests accept `application/fhir+json`. Resource types
and IDs are validated against safe patterns before any path is built, and
search parameters are typed and allowlisted. The adapter never follows
absolute paging links: when a search Bundle carries a `next` link the call
fails with a `truncated` error instead of silently returning a partial
first page. Reads map 404 to `None`. Writes use idempotent `PUT` with the
resource ID. Transactions post the Bundle unchanged to the base URL so the
server executes it atomically, and every entry of the transaction response
is inspected for error status or error `OperationOutcome`. Failures return
structured safe codes without PHI diagnostics; HTML error pages (for
example an infrastructure 401 page) collapse to a safe auth error.

No `/metadata` capability probe runs at startup. The native FHIR endpoint
is reachable only from the bridge process, never from B2.

## SQL prerequisites

```sh
RAKATHON_IRIS_SQL_HOST=127.0.0.1
RAKATHON_IRIS_SQL_PORT=1972
RAKATHON_IRIS_SQL_NAMESPACE=HOSPITALNS
RAKATHON_IRIS_SQL_USER=SQL_USER_PLACEHOLDER
RAKATHON_IRIS_SQL_PASSWORD=changeme
RAKATHON_IRIS_SQL_SCHEMA=FSB
```

The superserver port is its own setting with default 1972. Portal ports
such as 32783 and 443 are refused, and ports must be in 1..65535. The SQL
host must be a literal loopback IP (`127.0.0.1` or `::1`); `localhost` is
rejected because it can resolve off-host. Native SQL runs bridge to local
IRIS over loopback only; unverified remote TLS is not implemented. Username
and password are excluded from `repr`. The driver
package is the optional `intersystems-irispython` extra (`import
iris.dbapi`); without it, SQL methods fail with precise `not_configured`
errors and never fall back to mock data. The default connection factory
calls `iris.dbapi.connect(hostname=..., port=..., namespace=...,
username=..., password=..., sharedmemory=False, timeout=10000)`; that
keyword shape follows prior research but is NOT verified against a live
driver in this repository (the driver is not installed here), so confirm
it during supervised on-site integration. Driver errors are wrapped into
safe codes without credentials. A connection factory is
injectable so tests run against offline fakes. Tables for tasks and ACK
state are owned by this store with fixed column projections configured by
operations; caller-supplied schema or table names are rejected unless they
match the safe identifier pattern, and all values travel as bound `?`
parameters with validated integer `TOP` limits. Task ACK uses
compare-and-swap on `version` in a single connection
(`UPDATE ... WHERE id = ? AND version = ?`, rowcount checked, bounded
retries, then `conflict`); there is no cross-process Python-lock shortcut.
Public task creation uses INSERT-only semantics and refuses to overwrite
an existing id, so a duplicate write can never erase ACK state. Schema
discovery reads the
standard `INFORMATION_SCHEMA.TABLES` and `INFORMATION_SCHEMA.COLUMNS`
views (`TABLE_SCHEMA`, `TABLE_NAME`, `COLUMN_NAME`, `DATA_TYPE`) scoped to
the configured schema only, is available to local operators only (it is
not a remote bridge operation), and never
invents columns. FSB schema availability on any given deployment is not
proven here; confirm it with your IRIS administrator. Table creation
happens only through the explicit `bridge-init-db` command, never at
startup, and the store never auto-creates FSB projections.

## Vector search

```sh
RAKATHON_VECTOR_ANON_ENABLED=0
RAKATHON_VECTOR_ANON_SCHEMA=ANON
RAKATHON_VECTOR_ANON_TABLE=ANON_VEC
RAKATHON_VECTOR_ANON_DIMS=384
RAKATHON_VECTOR_ANON_SQL_USER=ANON_SQL_USER_PLACEHOLDER
RAKATHON_VECTOR_ANON_SQL_PASSWORD=changeme
RAKATHON_VECTOR_PATIENT_ENABLED=0
RAKATHON_VECTOR_PATIENT_SCHEMA=HOSP
RAKATHON_VECTOR_PATIENT_TABLE=PAT_VEC
RAKATHON_VECTOR_PATIENT_DIMS=384
RAKATHON_VECTOR_PATIENT_SQL_USER=PATIENT_SQL_USER_PLACEHOLDER
RAKATHON_VECTOR_PATIENT_SQL_PASSWORD=changeme
```

Anonymized and patient vector stores use separate schemas, tables,
dimensions, credentials, and connection factories. Each enabled store
needs its own SQL username (distinct from the task user and from each
other) on the same loopback superserver (same host, port, namespace);
optional `_SQL_HOST/_SQL_PORT/_SQL_NAMESPACE` overrides must match the
task store exactly. An enabled store without its own credentials refuses
to start. The task superuser is never reused for vector stores, and
vector execution stays disabled (`not_configured`) unless every piece is
explicitly configured. The
anonymized store stays disabled unless it holds explicitly synthetic data
or independently reviewed anonymized data; synthetic-only seeding is
enforced for the demo path, the anonymized query path additionally
requires `synthetic_only` configuration and refuses anything else, and
pseudonyms are never relabeled as anonymized. The vector API takes the B2 query string, parses it as a JSON
array of finite floats with exactly the configured dimension count, and
issues `ORDER BY VECTOR_COSINE(vec, TO_VECTOR(?, FLOAT)) DESC` with the
comma-joined vector as a bound parameter. No embedding provider is called.
Patient-channel hits resolve their resource references through the
configured FHIR adapter (B2 OUT1 FHIR); the anonymized channel never joins
patient data (OUT2 stays anonymized).

## Screening table (P3, bridge side only)

`b2/iris/screening_sql.py` (`ScreeningSqlStore`) stores the 25 raw screening
columns as bounded `VARCHAR` with `INVITATION_ID` as the primary key. The table
is created only by the explicit `screening-init-db` command on the bridge
host, never at startup. `INVITATION_ID` is `VARCHAR(64)` (`INVITATION_ID_WIDTH`)
so the longest legal `INV`-plus-32-digits value fits; widen an older narrower
column non-destructively in place instead of recreating it, never drop user
data, and never run real DDL outside the explicit init path. Imports arrive as closed `screening.import` batches
(`1..500` rows, inside the existing 512 KiB encrypted envelope): each batch is
validated against the shared screening schema, committed once, and rolled back
on any failure. New keys insert, identical rows skip, changed rows raise
`conflict` and abort the batch. Queries arrive as closed `screening.query`
arguments with an allowlisted projection and equality filters, bound `?`
parameters, a validated `TOP` cap, and an IRIS-side offset cap of 5000 (the
archive MOCK allows deeper offsets). Replies carry counts only for imports and
bounded rows for queries. Re-running an import is idempotent. Live IRIS
behavior is designed but NOT VERIFIED; offline fakes prove DDL shape, binding,
idempotence, conflict rollback, and caps.

```sh
rakathon-backend screening-init-db
rakathon-backend screening-import --source /srv/data/screening.zip --batch-size 500
```

## Bridge wiring

```sh
RAKATHON_ALLOW_IRIS_EGRESS=1
RAKATHON_BRIDGE_URL=https://bridge-hospital.example/rpc
RAKATHON_BRIDGE_ALLOWLIST=https://bridge-hospital.example/rpc
RAKATHON_BRIDGE_KEY_FILE=/run/rakathon/bridge.key
RAKATHON_BRIDGE_KEY_ID=b2-iris-01
```

## Bridge wiring

Start the trusted side next to IRIS, then point B2 at it:

```sh
rakathon-backend bridge-serve --bind 127.0.0.1 --port 8765
rakathon-backend serve --storage bridge --runtime-dir /tmp/opencode/rak-demo
```

`bridge-serve --mock-storage` runs the same encrypted envelope against a
local memory store for offline tests and reports mode `mock`. Table setup
is a deliberate manual step: `rakathon-backend bridge-init-db`.

## Direct FHIR mode (opt-in, user-approved HTTPS boundary)

`serve --storage iris-fhir` is an explicit opt-in that talks FHIR R4
directly to the exact literal `https://iris.racek.xyz/fhir/r4` over
verified TLS. Any other host, scheme, path, port (including an explicit
443), query, fragment, userinfo, or percent-encoded form is refused, and
`RAKATHON_IRIS_FHIR_VERIFY_TLS=0` is rejected instead of silently
upgraded. Proxies are isolated (`trust_env` off), redirects are never
followed, and request paths stay relative resource paths. `bridge-serve`
never opts into this mode. Credentials come from a private 0600 `iris.env`
file holding only the five `RAKATHON_IRIS_FHIR_*` keys (placeholders in
`iris.env.example`); the file is git-ignored and process env wins.

```sh
uv run rakathon-backend serve --storage iris-fhir --env-file iris.env \
  --runtime-dir /tmp/opencode/rakathon-live
```

`FhirOnlyStorage` delegates FHIR create/read/update to the real adapter
through the authenticated B4 → B6 → B2 path. Delete is not a product API
and exists only as owned test-id cleanup inside
`scripts/verify_iris_live.py`. SQL, vector search, and tasks stay
`not_configured` (fail closed, never mock fallback), the screening archive
may still mount separately as local data, and the task watchdog is off in
this mode. Search supports an additive `serverTotal` alongside the legacy
`total`; an explicit `_summary=count` request reports the server total.
Live proof prints aggregate codes/modes/counts plus the synthetic probe id
only. Prefer a dedicated least-privilege FHIR user over the IRIS superuser.

## Security limitations

- The bridge key authenticates the B2 service process, not the clinician.
  Per-user checks still run in B2 via B6 on every request.
- Error paths are redacted to safe codes; bodies from IRIS, SQL text, and
  request payloads never surface.
- Base-URL switching between hospitals is a configuration change of the
  trusted bridge, not a B2 feature; each deployment keeps its own key.
- Live behavior against IRIS 2026.1 / FHIR R4 is designed but NOT
  VERIFIED. Treat every SQL shape and FHIR interaction above as a contract
  to confirm during supervised on-site integration.
