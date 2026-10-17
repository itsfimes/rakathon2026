# Permanent converter uploads (demo, authenticated)

One upload button/dropzone accepts any non-executable file. Originals
are permanent and byte-identical and always travel alongside the FHIR
and internal output, even on failure. No FHIR writes ever happen from
this lane; review flags never import anything.

## Enable and run

```sh
# one-time: persistent dir OUTSIDE the worktree/runtime, 0700;
# store key is auto-generated at <store>/store.key (0600).
rakathon-backend auth-serve --auth-store demo --auth-dir /priv/auth \
  --origin http://127.0.0.1:5173 --allow-loopback-http \
  --storage mock --runtime-dir /tmp/demo-runtime \
  --converter-enable --converter-store /persistent/uploads \
  --converter-secret-file /private/azure-key-0600 \
  --converter-image rakathon-converter:latest
```

- Default is OFF: without `--converter-enable` plus `--converter-store`,
  `GET /api/v1/uploads/capabilities` reports
  `{enabled:false, reason:"converter_disabled"}` and upload routes 503.
- Without the Azure secret the service still retains files honestly:
  capabilities report `enabled:true, aiAvailable:false`, jobs run the
  deterministic decoders and end `manual-review` with
  `planner_fallback:no-agent`. The global AI assistant stays off; the
  converter passes `--allow-azure` to the launcher with the mounted key
  only, never copies other secrets and never turns AI server mode on.
- The converter store must live outside the runtime dir (startup
  refuses `--converter-store` inside `--runtime-dir`). Backups and
  durability of `/persistent/uploads` are operator-owned and separate
  from tmp demo runtime state. The encryption key (`store.key`, 0600)
  is never printed, logged, committed, or inlined in config.
- Jobs launch outside the HTTP thread (single-flight worker pool);
  Docker is host-controlled (no socket inside the container, no repo
  root or live auth dir mounts). Only the user-agreed Docker service
  is used; no host sudo packages are installed. The running service is
  untouched until the parent deploys this lane.

## API shape (all JSON `version:1` unless binary)

- `GET /api/v1/uploads/capabilities` (authenticated, role-checked):
  `{version:1, enabled, maxFileBytes:5242880, reason|null,
  aiAvailable}`. Reasons: `converter_disabled`, `forbidden_role`.
- `POST /api/v1/cases/{caseId}/uploads` with
  `Content-Type: application/octet-stream` and `X-Upload-Name`
  (percent-encoded UTF-8 filename): returns `202 {version:1, job:{...}}`.
  5 MiB cap only on this route (other JSON stays 16 KiB in, 1 MiB out).
  Auth, verified-identity B6 `document.upload` (admin/coordinator/
  clinician only, viewer 403), explicit case access, and duplicate
  content-length/type/name/csrf checks run before persist/enqueue.
  Queue: 1 running global plus bounded queue (4 global, 2 per user);
  full queues answer 429.
- `GET /api/v1/uploads/{uuid}`: metadata plus events and counts, no
  PHI raw text: `{version:1,
  job:{id, caseId, filename, sha256, sourceUrn, detectedType, status,
  createdAt, events, eventCount, counts, recipeReuse, newFormat,
  plannerMode, model:{providerId:"rakathon-azure",
  model:"gpt-6-luna-dz-eu", mode}}}`.
- `GET /api/v1/uploads/{uuid}/original`: exact original bytes,
  `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`,
  never inline HTML/SVG.
- `GET /api/v1/uploads/{uuid}/export`: ZIP with the original EXACT
  bytes plus `result.json`, `bundle.json` (when valid),
  `provenance.json`, `attempts.json`; unsupported jobs export the
  original plus an honest status instead of a bundle.
- `GET /api/v1/cases/{id}/uploads`: the caller's own jobs for that
  case (survives refresh). Owner-only reads: other users get 404, and
  B7 session 401 keeps earlier capability behavior intact.
- Job `status`: `queued|running|complete|manual-review|failed|
  cancelled|interrupted`. Restart reloads jobs and marks
  queued/running ones `interrupted` honestly without losing raw bytes.
  No original TTL or deletion; only scratch temp dirs are cleaned.
- Sealed versus plaintext: original bytes and the `result`/`provenance`/
  `bundle` blobs are sealed with the store key; `index.json` and per-job
  `meta.json` stay plaintext JSON carrying job metadata (ids, filenames,
  status, counts) and are private only through filesystem modes (store
  dir `0700`, files `0600`).

## Evidence the parent live-checks (hosted API, no browser)

- Provider/model/mode: every job exposes
  `model:{providerId:"rakathon-azure", model:"gpt-6-luna-dz-eu",
  mode}` over the exact `/openai/v1` endpoint with the `api-key`
  header via the existing verified adapter; offline runs stay
  key-unavailable and never fake Azure output.
- Parent plan after this terminal: known synthetic PDF, one unknown
  encoded file, then a repeat upload proving `recipeReuse:true` from
  the guarded cache, all through the hosted API with no clinical
  files. Keep live-assistant globally off.

## Oracle review note

Reuse the passing suites below with scoped re-runs; do not rerun the
unchanged 430 frontend tests or prior Docker checks unless the image
changed. See `docs/converter.md` for the adaptive lane and the
terminal report for exact commands.
