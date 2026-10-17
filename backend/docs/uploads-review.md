# Uploads manual review lane

Manual review edits a retained model candidate, then imports it only
after explicit human approval and a verified IRIS receipt. No clinical
write ever happens from draft saves.

## Routes (all `version:1`)

- `GET /api/v1/uploads/{uuid}/review` returns
  `{version:1, review, approvalEnabled, approvalReason}`. `review` is the
  `ReviewStore` public view with `candidateText`, `validation`,
  `counts`, `patientRef`, `sourceUrn`, `sourceSha256`, `caseId`,
  `modelDraftAvailable`, `modelDraftReason`, `importReceipt`,
  `approvalId`. `approvalReason` is `null` when enabled, else one of
  `already_imported`, `import_locked`, `invalid_candidate`,
  `not_configured`, `forbidden`, `unavailable`.
- `GET /api/v1/uploads/{uuid}/review/model` returns
  `{version:1, modelOutputText:string|null}`. Raw model text only; the
  review payload carries the editable candidate.
- `POST /api/v1/uploads/{uuid}/review/draft` with exact JSON
  `{revision:int, candidateText:string}` returns `{version:1, review}`.
  Invalid FHIR stays savable with `validation.valid:false` and never
  writes clinical data.
- `POST /api/v1/uploads/{uuid}/review/approve` with exact JSON
  `{revision:int, patientConfirmed:true}` returns `{version:1, review}`
  only after a verified IRIS receipt. No bundle, user, role, or receipt
  is accepted from the request; the server uses the claimed prepared
  bundle plus the verified identity.

## Guards and errors

- Every path rechecks owner plus fresh `document.upload` and case
  access through the base upload guard. Approve additionally checks
  fresh `document.approve` and import readiness before claiming.
- Mock storage (`--storage mock`) reports `approvalEnabled:false`
  with `not_configured`; approve answers `503 not_configured` and
  never pretends a real success.
- All review JSON is strict: duplicate keys, NaN/Infinity,
  non-object bodies, and additional keys are rejected. `revision`
  must be a non-bool int; `patientConfirmed` must be `true`.
- Statuses: `422 invalid_schema`, `409 conflict` with
  `currentRevision`, `403 forbidden`, `404 not_found`,
  `503 not_configured/unavailable`, `429 import_busy/busy`,
  `413 too_large`, `405 method_not_allowed`.
- One global non-blocking import gate runs at a time; a busy gate
  answers `429`. An already-imported revision replays idempotently
  without reinvoking the importer. Known failures
  (`ContractError`, `AuthError`) record `import-failed` and stay
  re-editable; transport, timeout, and unknown responses record
  `import-uncertain` without a false approval. An aborted HTTP reply
  never rolls back an approved transaction; the receipt persists.

## Runtime wiring

- `runtime/review_bridge.py` builds the importer with
  `make_review_importer(runtime_dir, web_token)`. It sends the verified
  user id via `web:auth` to `b4 document.approve` with the exact
  claimed `{bundle, context}`, a `135s` client timeout, and checks
  source, action, `FHIR` kind, `approvalId`, receipt shape, and counts.
  Readiness is `args.storage == "iris-fhir"`; the assistant AI flag is
  untouched.
- `runtime/upload_wiring.py` instantiates `ReviewStore` and wraps the
  base `UploadRoutes` with `ReviewUploadRoutes`, dispatching review
  paths first and delegating everything else to the base handler.
- Successful metadata and case-list jobs gain an optional
  `review:{state, revision, valid, updatedAt, reviewedBy}` badge for
  list views. Export appends `review-draft.txt`, `review.json`,
  `review-audit.json`, plus `approved-bundle.json` and
  `import-receipt.json` once imported, without overwriting the base
  files and within the unchanged `12MiB` cap.

## Body caps

- `POST .../review/draft` and `POST .../review/approve` accept up to
  `768KiB` (`MAX_REVIEW_BODY_BYTES`) to fit a `256KiB` candidate with
  JSON escaping. All other JSON stays `16KiB` in and `1MiB` out; file
  uploads stay `5MiB`; `Content-Type: application/json` is enforced in
  the review handler. Proxy, cookie, CSRF, and exact-origin checks are
  unchanged.
