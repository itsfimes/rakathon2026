# Standalone converter worker (Dockerized OpenCode coding agent)

Bounded per-job CLI worker. One input file per job. Deterministic local
parsing extracts text first; at most one model call translates it to
FHIR R4. This is a constrained converter, not autonomous script
generation: unknown cases become `manual-review`, never guesses.

## Model and endpoint (fixed)

- Provider `rakathon-azure`, model `gpt-6-luna-dz-eu`, exact base URL
  `https://apim-rakathon-q7146n.azure-api.net/openai/v1`.
- Reuses `b5/opencode/{process,client,config,validation}` (pinned binary
  `2.0.31`) and the protocol in `docs/opencode.md`: session create with
  `model.providerID/id`, `/generate` with `prompt`, `/interrupt`,
  `DELETE` session. Tool permissions are all deny; the agent has no
  filesystem, shell, or network tools.
- One model call per job, no repair loop, no automatic retries.
  Provider errors and timeouts kill the child, delete the session, and
  leave no orphan container. Budgets: startup 30s, inference 180s,
  total ~240s, launcher outer wall 300s.
- No direct Azure fallback and no mock-as-real output. Offline
  `--check`/`--extract` modes use `--network none`.

## Inputs and limits

- Accepted: `.docx` / `.txt` / `.json` / `.csv` / `.pdf` (text layer
  only). Caps: 5 MiB raw, 20 PDF pages, extracted text <= ~60 KiB. The
  existing DOCX extractor cap (256 KiB package) is honored.
- PDF uses Poppler `pdftotext`/`pdfinfo` inside the image via bounded
  subprocess. No new host dependency is needed.
- Rejected (non-zero exit, safe artifact, never a bundle): encrypted or
  malformed PDFs, oversized inputs, symlinks, special files, recursive
  archives, binary text, empty text. Unknown suffixes are no longer
  rejected up front: content-based detection (magic bytes, not the
  filename suffix) routes them through the bounded adaptive lane
  (see below); only undecodable bytes end as honest `manual-review`
  after the recorded attempts. Executable
  content (ELF, PE/MZ, Mach-O, script shebang) is rejected by
  magic-byte sniffing of the raw bytes, so renaming an executable to
  `.pdf` / `.txt` / `.csv` does not bypass the check. Executable
  suffixes (`.exe`/`.dll`/`.so`/`.bat`/`.ps1`/`.sh`/...) are rejected
  even with benign bytes, and ZIP members are inspected for
  executable/macro danger before any text is taken.
- Images and scans (`.png` / `.jpg` / `.tiff`, PDFs without a text
  layer) become a stable `manual-review` artifact. No OCR is attempted;
  Tesseract is not reliable for handwriting, so no general OCR is
  claimed and text is never fabricated.
- Injection inside the document is treated as untrusted data, flagged in
  `issues`, and never followed.

## Extraction boundary (extensible)

`converter/extract.py` owns the single entry point `extract_file`:
validate path, dispatch on suffix, return page-labelled text plus
SHA-256 hashes plus a deterministic identity-conflict signal. Decoders
register per suffix in the `DECODERS` table via `@decoder(".ext")`, so a
future adaptive lane can add bounded multi-approach format recipes
(saved after validated success, never carrying PHI or keys) without
touching the worker core. Anything a decoder cannot handle must raise
`ManualReviewNeeded` (review, no AI call) or `ConverterError`
(reject); unknown formats are fingerprinted (MIME plus magic category
plus structural root plus member patterns, never patient values) so a
later orchestration pass can retry them instead of giving up. Success versus manual-review taxonomy:

- `complete` / `incomplete`: model output passed strict validation and
  every clinical resource carries page-literal evidence.
- `manual-review`: images/scans, conflicting patient identity across
  pages, missing Azure opt-in or secret, agent failure, invalid model
  output, or rejected input. No AI call is made for unsupported input,
  and invalid AI output yields a non-zero exit with no `bundle.json`.

Conflicting patient identity (distinct `MRN:` values across pages, as in
the gold tricky fixture) forces `manual-review` deterministically, even
without any model call.

## Output contract

`out/result.json` always; `out/bundle.json` only for a valid bundle;
`out/provenance.json` always. Result keys: `status`
(`complete`/`incomplete`/`manual-review`), `bundle` (object or null),
`issues`, `evidence`, plus `needsReview: true`, `writeEligible: false`,
`persistence: "not-written"`. A `complete` status means structural
validity only, never clinical correctness.

- Strict JSON: no fences, no NaN/Infinity, no duplicate keys, exact
  keys and types with size caps. Structural checks reuse
  `common/fhir.check_bundle` (allowlist of 8 clinical types, closed
  references, statuses, URL guard); `OperationOutcome` is validated when
  used. Model-supplied provenance is forbidden (extra keys rejected);
  the wrapper attaches `meta.source` (`urn:sha256:<input>`) and records
  the extract hash separately without trusting model provenance.
- Every clinical resource needs evidence with `resourceType`/`id`,
  `sourcePage`, and a `literalQuote` present on that source page (an
  optional `field` JSON pointer must resolve). Source quotes locate
  facts; they do not prove every fact. Unknown codes, units, and dates
  are omitted, never invented (no invented LOINC).
- Writes are atomic with mode 0600 into a new or empty owned directory
  (no overwrite, no symlinks, no stale bundle on failure). Stdout
  carries only status, resource counts, runtime, and model presence: no
  PHI, keys, or raw model logs.

## Originals versus derived outputs (retention)

Caller input is never deleted, moved, or modified: the worker only
reads it (read-only bind mount in the container, read-only file access
directly). Standalone input retention is caller-owned: originals are
permanent and byte-identical, and they travel alongside the FHIR and
internal data produced from them.

Everything under the output directory is a temporary per-job derivative
(extracted text, `result.json`, optional `bundle.json`,
`provenance.json`), not the original. Every artifact carries the source
SHA-256 (`sourceSha256`) and filename so durable followup storage can
store the original bytes plus the hash and reference the candidate
FHIR/job from them. Unsupported and rejected files are fingerprinted
the same way (hash plus filename, no bundle), so they can be retained
too. Nothing here implies originals are ephemeral, and no broad
API/storage expansion is included in this lane.

## Runtime and launcher

- Image: Python 3.13 slim, non-root user, pinned `opencode 2.0.31`
  verified with `--version` at build. The host binary is staged into an
  explicit temp build context (never host config or credentials); the
  context is a strict allowlist (Dockerfile, binary, `pyproject.toml`,
  `README.md`, `src`), so datasets, `.git`, `.env`, and runtime state
  are excluded by construction. The package installs pinned runtime
  dependencies reproducibly.
- Container: fresh `HOME`/`XDG_*`/`TMPDIR` under per-job tmpfs,
  read-only rootfs, `cap-drop ALL`, `no-new-privileges`, pid/memory/cpu
  limits, no published ports, no Docker socket, no repo-root mount.
  The container runs as the caller's host uid/gid (still non-root, so
  output files stay caller-owned); the image default user is the
  non-root `converter` account (uid 65532).
  Input mounts read-only under `/work/input/<filename>` (suffix kept so
  the decoder dispatch sees it), output read-write, secret file (0600,
  outside the checkout) mounts read-only at `/run/secrets/azure_api_key`;
  the key enters the container environment only, never an image layer,
  build arg, or CLI literal. Unexpected failures print only a static
  error code to stderr, never tracebacks with paths or content.
- Azure mode uses bridge networking explicitly without claiming an
  egress firewall or allowlist. Production `manual-review` outputs need
  human approval before any downstream use.

```sh
python3 backend/scripts/run_converter.py --input f.pdf --output out/ --build
python3 backend/scripts/run_converter.py --input f.pdf --output out/ \
  --allow-azure --secret-file /path/to/key0600
python3 backend/scripts/run_converter.py --input f.pdf --output out/ \
  --extract --offline
```

Direct (no Docker) runs: `uv run python -m rakathon_backend.converter.cli
--input f.pdf --output out/ [--extract | --check]`.

## Adaptive unknown-format lane (bounded)

- Content detection (`converter/detect.py`) classifies by magic bytes,
  never the suffix: pdf / zip / rtf / html / xml / hl7 / text / binary /
  executable. The audited DSL (`converter/adaptive.py`,
  `converter/archive.py`) only offers: charset decode (utf-8, utf-16,
  cp1250) with a plaintext readability threshold, XML without
  DTD/entities/external refs, HTML tag stripping with no active
  elements, RTF limited text, ZIP bounded member text, XLSX bounded
  sheet XML, HL7v2 segment text. At most 3-5 approaches per file
  inside a ~180s decoding budget plus one FHIR call.
- Unknown suffixes go through OpenCode once as a PLANNER
  (`converter/planner.py`, `converter/unknown.py`): the agent sees only
  detector metadata plus a bounded sample as untrusted data and the
  allowed primitive list, and must return strict JSON DSL
  (`{"version":1,"steps":[...]}`); the host validates the recipe and
  executes deterministic steps. No arbitrary generated code, exec, or
  shell. Without Azure (no `--allow-azure` plus 0600 secret) the worker
  records `planner_fallback:no-agent` and runs the same deterministic
  attempts. Budget: max 1 planner call plus 1 FHIR call for unknown
  files, 1 call for known formats, no automatic repair, ~300s wall.
- Recipes are cached (`RAKATHON_RECIPE_CACHE_FILE`, upload store
  `recipes.json`) only after structurally validated extraction plus a
  successful FHIR output, keyed by fingerprint, storing decoder
  primitive names and versions only: no PHI, filenames, headers,
  patient values, quoted content, or generated code. Every cache hit is
  re-executed against the current file and must still meet the
  readability bar, so a malicious same-extension file cannot false-hit.
  Attempt events (`code:status` with timestamps), `recipeReuse`,
  `newFormat`, and `plannerMode` travel in `result.adaptive` and
  `provenance`; raw model text is never logged. The container recipe
 mount stays read-only by design, so promotion back to the shared
 cache is host-owned after a validated FHIR run: the standalone CLI
 writes the cache only when the cache path (or its parent) is
 writable, `RAKATHON_RECIPE_CACHE_READ_ONLY` is unset, and the
 pending recipe passes the strict DSL parse first. Malformed or
 enriched recipes are never learned and carry no PHI, filenames, or
 quoted content.
- Unsupported endings (`binary_no_extract`, `unknown_no_extract`,
  `encrypted_no_extract`, empty inputs) are `manual-review` after the
  recorded attempts: never a faked conversion, never invented facts.
  The demo makes no OCR promise for handwriting scans.

## Validation scope

FHIR checks are the shared R4-subset validator (`common/r4` model
checks), not full HL7 terminology or profile validation; no
terminology, profile, or clinical-fidelity claims are made. The
optional official HL7 validator was not wired in (large offline
download, not mandatory).

Tests in `tests/test_converter_*.py` own this lane: malformed input,
PDF pages, symlinks, oversize, no-OCR, mock-model-only-offline (clearly
marked, never demo output), injection, strict output, evidence,
unclosed references, failed writes, secret config, default-off Azure,
timeouts, and Docker flags. Future Oracle reviews should reuse these
completed tests with scoped re-runs, not a global agent-config change.
