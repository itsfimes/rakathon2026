# Encrypted bridge (B2 trusted egress)

B2 normally runs on the mock memory store with no network. The encrypted
bridge is the only approved path for B2 to reach hospital IRIS data, and it
is disabled by default. Every identity and action argument travels inside
Fernet ciphertext. URLs, headers, and logs never carry plaintext.

Official source for the crypto recipe:

- `https://cryptography.io/en/latest/fernet/`
- `Fernet.generate_key()`, `encrypt(bytes)`, `decrypt(token, ttl=...)`,
  `InvalidToken`. No handshake primitives are hand-written here.

## Protocol

Outer JSON carries only routing metadata:

```json
{"keyId": "cfg-id", "token": "<fernet>"}
```

Inner request (encrypted):

```json
{
  "version": 1, "keyId": "cfg-id", "direction": "request",
  "requestId": "<uuid>", "operation": "tasks.write",
  "arguments": {"task": {}}
}
```

Inner response (encrypted) echoes `requestId` and `operation`:

```json
{
  "version": 1, "keyId": "cfg-id", "direction": "response",
  "requestId": "<same>", "operation": "tasks.write",
  "result": {"task": {}}
}
```

Safe failures use `{"error": {"code": "...", "message": "..."}}` with
redacted messages. Downstream HTTP bodies, SQL text, and IRIS payloads are
never copied into errors.

## Allowlisted operations

`fhir.write`, `fhir.read`, `fhir.search`, `tasks.write`, `tasks.read`,
`tasks.ack`, `vector.search`, `health`. There is no
arbitrary SQL operation, no caller-supplied URL fetch, no remote schema
discovery, and no resource path
traversal. Local SQL schema discovery (`IrisSqlStore.schema_discover`,
scoped to the configured schema) stays available to the bridge operator
process only and is never exposed over the encrypted protocol. FHIR
transaction request URLs must be relative resource paths
such as `Patient/abc`; absolute URLs and unsupported methods are refused.

## Keys

One pre-shared Fernet key per B2 deployment:

```sh
rakathon-backend bridge-keygen --path /run/rakathon/bridge.key --key-id b2-iris-01
```

The command prints only the path and key ID, never the key. Key files must
be owned by the runtime user, mode `0600`, and must not be symlinks or
group/world readable. Generation uses atomic exclusive create, so an
existing file is never overwritten. Both endpoints store the same key file
through secure deployment. The key never appears in stdout, logs, source,
or env templates. The key ID is nonsensitive configuration.

Rotation means replacing the key file on both ends and restarting both
processes. There is no forward secrecy: anyone holding the key can decrypt
captured tokens. There is no identity beyond key possession.

The bridge operator is trusted: whoever holds the key can issue any
allowlisted operation, including `tasks.ack` for any asserted user id.
`tasks.ack` callers are checked against an allowlist of user ids taken
from the server policy users (plus a strict id shape and task membership
in the store), and every bridge mutation (`fhir.write`, `tasks.write`,
`tasks.ack`) is appended to a local JSONL audit file (mode `0600`) with
`timestamp`, `requestId`, `operation`, `assertedActor`, and `status` only:
no patient payload, no credentials. The `tasks.ack` actor is recorded as
asserted by the authenticated B2 service, not independently verified. This
is a minimal local trail, not a full audit system; the replay journal
limitation below still applies.

## Replay

The server keeps a thread-safe process-local cache keyed by
`(keyId, requestId)`. A request ID is consumed after authenticated
validation and before storage, so a captured token cannot be replayed while
the entry lives. Cache TTL is token TTL plus 60 seconds of Fernet clock
skew. Unexpired entries are never evicted to make room: when the cache is
full, new requests are refused closed.

The cache is process-local. After a restart, tokens issued before the
restart can be replayed until their Fernet TTL expires. This prototype
limitation is explicit: remote production use is unsafe without either a
startup quarantine longer than token TTL plus skew, or a durable replay
journal. SQLite would be acceptable only as a replay journal with mode
`0600`, never as disguised IRIS storage.

## Client rules

The bridge client (`EncryptedBridgeStorage`) posts to one approved HTTPS
URL ending in `/rpc`, with `trust_env` disabled, redirects disabled,
certificate verification on, finite connect/read timeouts, and a capped
response body. Plain HTTP is refused except for an explicit test-only flag
that additionally requires a loopback hostname or IP. Configuration needs
`RAKATHON_ALLOW_IRIS_EGRESS=1`, the bridge URL, an optional origin
allowlist containing that URL, the key file, and the key ID. Anything
missing fails before any networking. The client never falls back to direct
FHIR or to memory storage on failure.

## Server rules

The bridge server is stdlib `ThreadingHTTPServer` bound to loopback by
default (demo use only, not a production server). It serves only
`POST /rpc`. Requests without `Content-Length`,
with chunked encoding, with duplicated `Content-Length`, or above about
1 MiB are refused. Each accepted connection gets a bounded per-request
socket timeout, so a declared but stalled body times out instead of
parking a worker forever. Concurrent request workers are capped by a
small semaphore and excess connections are refused closed. There is no
unauthenticated plaintext health endpoint:
liveness uses the encrypted `health` operation because IP health checks
must also authenticate. Access and body logging are suppressed.

## Nginx deployment

TLS terminates at the reverse proxy. Nginx proxies ciphertext to the
loopback bridge without decrypting it:

```nginx
location = /rpc {
    proxy_pass http://127.0.0.1:8765;
    proxy_http_version 1.1;
    client_max_body_size 1m;
}
```

Intermediaries, including nginx, cannot decrypt tokens. The trust boundary
is bridge to local IRIS over loopback. The native FHIR endpoint of IRIS is
never exposed to B2 directly; only the trusted bridge process talks to it.

## Known limitations

- Fernet timestamps are visible to anyone holding a token. Payload
  confidentiality and integrity hold, but token age leaks.
- Key possession authenticates the B2 service, not the hospital end user.
  End-user authorization still happens in B2 through B6 on every request.
- No forward secrecy across key rotation windows.
- Replay resistance is process-local (see above).
- Live integration against a real IRIS instance is NOT VERIFIED. All
  gateway behavior is proven with offline fakes and loopback tests only.
