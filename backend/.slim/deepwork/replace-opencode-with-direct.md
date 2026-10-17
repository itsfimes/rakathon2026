# Deepwork: Replace OpenCode subprocess with minimal direct harness

## Current state

- B5 has three runtime AI modes: `mock`, `opencode`, `direct`.
- `b5/opencode/` is a subprocess wrapper around the OpenCode CLI binary that exposes a fake OpenAI-compatible HTTP endpoint. It is 268+ lines of process lifecycle, port reservation, env scrubbing, and readiness polling.
- `b5/direct.py` + `b5/direct_http.py` already implements a real HTTP transport to Azure OpenAI / OpenAI-compatible `/chat/completions`. It validates endpoints, auth headers, JSON schema response format, retries on 429, and parses responses. This is the actual minimalistic harness the user wants.
- `runtime/ai_factory.py` and `runtime/legacy_ai.py` are stringy `importlib` shims that load the OpenCode adapter. They hide dependencies and lose typing.
- Clinical context is built in `web/clinical_context.py`, `web/clinical_facts.py`, `web/clinical_codes.py`, and the B5 `SYSTEM_MESSAGE` lives in `b5/conversation_policy.py`. There is no `b5/prompts.py`.
- The CLI still advertises `--ai opencode`, `ai-check` validates OpenCode config, and tests are scattered across `test_b5_opencode_*.py`, `test_b5_azure_*.py`, `test_app_ai.py`, `test_cli_ai.py`, `test_s4_runtime.py`, `test_direct_import_isolation.py`.

## Goal

1. Remove OpenCode mode entirely; make `direct` the only live provider path.
2. Re-use the existing `direct.py` config schema (`RAKATHON_AI_PROVIDER_KIND`, `RAKATHON_AI_BASE_URL`, `RAKATHON_AI_MODEL`, `RAKATHON_AI_AUTH_SCHEME`, `RAKATHON_AI_API_KEY`, `RAKATHON_AI_REQUEST_TIMEOUT`) so the harness “steals creds/model id from the ingestor”.
3. Improve system prompt / prompt construction for better clinical FHIR context injection.
4. Delete `b5/opencode/`, `runtime/ai_factory.py`, `runtime/legacy_ai.py`.
5. Update CLI, runtime application, ingest, commands, tests, and docs.
6. Keep `mock` mode fully functional for offline demo/tests.

## Files to modify / delete

### Delete
- `src/rakathon_backend/b5/opencode/` (whole package)
- `src/rakathon_backend/runtime/ai_factory.py`
- `src/rakathon_backend/runtime/legacy_ai.py`
- `scripts/opencode_isolated_smoke.py`
- `docs/opencode.md`
- `tests/test_b5_opencode_process.py`
- `tests/test_b5_opencode_config.py`
- `tests/test_b5_opencode_client.py`
- `tests/test_b5_opencode_adapter.py`
- `tests/test_b5_azure_config.py`
- `tests/test_b5_azure_binary.py`
- `tests/test_app_ai.py`
- `tests/test_cli_ai.py`
- `tests/test_s4_runtime.py`
- `tests/test_direct_import_isolation.py`

### Modify
- `src/rakathon_backend/b5/__init__.py` — drop OpenCode re-exports
- `src/rakathon_backend/b5/conversation_policy.py` — improve system prompt with clinical-context guidance
- `src/rakathon_backend/b5/direct.py` — keep as adapter, maybe move translate prompt into a dedicated `b5/prompts.py`
- `src/rakathon_backend/b5/direct_http.py` — keep; possibly minor robustness improvements
- `src/rakathon_backend/b5/gateway.py` — drop opencode-specific assumptions
- `src/rakathon_backend/runtime/tokens.py` — `AI_MODES = ("mock", "direct")`
- `src/rakathon_backend/runtime/application.py` — validate only `mock`/`direct`; drop “opencode requires adapter” text; allow direct mode to auto-build `DirectAdapter` from env when adapter not passed
- `src/rakathon_backend/runtime/commands.py` — remove `cmd_ai_check`; make `cmd_serve` construct direct adapter from env
- `src/rakathon_backend/runtime/ingest.py` — remove opencode branch; construct direct adapter from env
- `src/rakathon_backend/cli.py` — remove `opencode` choice and `ai-check` subcommand
- `src/rakathon_backend/web/config.py` — if it references OpenCode, update to `direct`
- `scripts/verify_iris_live.py` — only if it references opencode mode
- `README.md`, `HANDOFF.md`, `docs/direct-ingestion.md` — remove opencode examples
- `pyproject.toml` — remove opencode script entry points if any
- Tests: keep `tests/test_b5.py` but switch test “mode” strings from `opencode` to `direct`; add focused tests for direct adapter/harness in `tests/test_b5_direct.py`

## Implementation phases

### Phase 1 — Remove opencode wiring (DONE)
- Deleted `b5/opencode/`, `runtime/ai_factory.py`, `runtime/legacy_ai.py`, `scripts/opencode_isolated_smoke.py`, `docs/opencode.md`.
- Updated `cli.py`, `tokens.py`, `application.py`, `commands.py`, `ingest.py`.
- Updated env examples and docs.
- Verification: ruff on changed files passed; repo-wide ruff/mypy have pre-existing errors.

### Phase 2 — Test migration/trimming
- Delete opencode-specific tests: `test_b5_opencode_*.py`, `test_b5_azure_*.py`.
- Migrate retained suites:
  - `test_app_ai.py`: replace opencode mode strings with `direct`; remove opencode-specific adapter tests.
  - `test_cli_ai.py`: use `direct` for parser/default tests; add rejection test for removed mode/subcommand.
  - `test_s4_runtime.py`: keep atomic config/write/health tests unrelated to opencode; drop opencode proxy tests.
  - `test_direct_import_isolation.py`: remove legacy branch but keep direct-import isolation check.
- Fix any direct-only breakages.

### Phase 3 — Prompt / context improvement
- Move translate prompt into `b5/prompts.py`.
- Improve `conversation_policy.py` system prompt with explicit clinical-context instruction.
- Add tests for prompt construction.

### Phase 4 — Validation
- Phase 1-3 complete.
- Run `mypy`, `ruff check`, `ruff format`, `pytest` and fix any new errors.

## Open questions
- Should the improved system prompt remain Czech only, or bilingual? (Default: keep Czech as it is user-facing in the app, but add structured clinical-context insertion rules.)
- Should we add JSON schema completion path to `b5/direct.py` beyond translation? (Default: keep current schema usage for `translate`; `complete` stays plain text.)
- Is `direct_http.py` robust enough, or do we need to add jitter/backoff, streaming, or larger byte budgets? (Default: keep current retry/timeouts, fix obvious issues if tests show them.)
