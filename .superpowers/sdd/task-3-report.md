# Task 3 — Memory lifecycle, account operations, and correlation logs

## Scope

- Worktree: `/home/ubuntu/hys/.worktrees/research-agent`
- Scope held to the Task 3 brief: daily memory cleanup scheduling, authenticated memory account operations, strict user-scoped RAG session keys, request/run correlation, and safe completion/runtime logs.
- No deployment, push, production-server action, network request, secret access, or external write was performed.

## Delivered behavior

- `ensure_fixed_crawl_schedules()` idempotently registers `cleanup-expired-agent-memory-daily` at 03:00 in `settings.TIME_ZONE`, with task exactly `agent_runtime.tasks.cleanup_expired_memory_task` and JSON empty args (`[]`).
- The account privacy screen now supports explicit authenticated memory saving through `save_explicit_memory`, caller-only JSON download as `memory-export.json`, and POST-only deletion scoped to the current user. Existing `/api/v1/memory` behavior remains intact.
- Authenticated optional RAG session keys are now strictly owner-scoped: another user's key cannot be adopted, read, or set as the current user's ask-page cookie. Anonymous short-lived sessions retain their existing behavior. Long-term `MemoryEntry` data is not added to RAG prompts automatically.
- Added nullable indexed `AgentRun.request_id` with migration `0011_agentrun_request_id` after `0010`.
- `CorrelationMiddleware` accepts only UUID request IDs (otherwise creates a server UUID), assigns `request.request_id`, returns `X-Request-ID` for normal, 404, and streaming responses, and emits one completion JSON record with exactly `request_id`, `run_id`, `method`, `path`, `status`, and `duration_ms`.
- Research create/retry preserves the first run's request ID under idempotency; replay records the replay request ID. Known research runs are attached as `request.agent_run_id` for completion correlation. Legacy `/ask/stream/` produces a distinct safe runtime-creation JSON record containing only its event name and request ID.

## TDD evidence

Production changes were preceded by focused tests and an observed red run.

1. Added the schedule, account save/export/delete, account session-isolation, research request/replay, middleware/header/404/log-whitelist, and streaming runtime-log tests.
2. Initial invocation `pytest ...` could not start because `pytest` was absent from `PATH`; the repository virtualenv was then used without installing anything.
3. Red command:

   ```text
   /home/ubuntu/hys/.venv/bin/python -m pytest aggregator/tests/test_schedule.py agent_runtime/tests/test_accounts.py agent_runtime/tests/test_research_runtime.py -q
   ```

   Result: `8 failed, 25 passed`. The failures were the intended missing daily schedule, account routes, `AgentRun.request_id`, correlation header/middleware, and safe streaming-log behavior.
4. The additional authenticated ask-page foreign-session test was added before its corrective change and observed red:

   ```text
   /home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_accounts.py::test_authenticated_ask_page_rejects_foreign_session_key -q
   ```

   Result: `1 failed`; the response set the foreign session key cookie. After the minimal owner-scope fix, the same test passed.

## Verification

- Focused suite:

  ```text
  /home/ubuntu/hys/.venv/bin/python -m pytest aggregator/tests/test_schedule.py agent_runtime/tests/test_accounts.py agent_runtime/tests/test_research_runtime.py -q
  ```

  Result: `35 passed`.
- Full suite:

  ```text
  /home/ubuntu/hys/.venv/bin/python -m pytest -q
  ```

  Result: `190 passed`.
- Django check:

  ```text
  /home/ubuntu/hys/.venv/bin/python manage.py check --settings=zhongbei_info.settings_test
  ```

  Result: `System check identified no issues (0 silenced).`
- Migration state check:

  ```text
  /home/ubuntu/hys/.venv/bin/python manage.py makemigrations --check --dry-run --settings=zhongbei_info.settings_test
  ```

  Result: `No changes detected`.
- Migration plan includes `agent_runtime.0011_agentrun_request_id` as `Add field request_id to agentrun`.
- `git diff --check` completed without whitespace errors.

## Notes

- The test/check output includes an existing LangGraph pending-deprecation warning; it does not report a failure or this task's code path.

## Review-fix addendum

### TDD evidence

Regression tests were added before the fixes for HTTPS redirects, authenticated export caching, authenticated ask-page memory saving, legacy streaming creation correlation, and non-HTTP legacy request IDs.

- Red command:

  ```text
  /home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_accounts.py::test_memory_export_contains_only_current_users_data_and_is_json_attachment agent_runtime/tests/test_accounts.py::test_authenticated_ask_page_exposes_explicit_memory_save_form agent_runtime/tests/test_research_runtime.py::test_streaming_ask_gets_correlation_header_and_safe_runtime_creation_log agent_runtime/tests/test_research_runtime.py::test_legacy_rag_runtime_gets_a_request_id_without_an_http_request agent_runtime/tests/test_research_runtime.py::test_https_redirect_has_correlation_header_and_completion_log -q
  ```

  Result: `5 failed`, as expected: no export cache directive, no ask-page save form, no post-creation legacy run correlation, legacy `AgentRun.request_id=None`, and HTTPS redirect without `X-Request-ID`.

### Changes

- Moved `CorrelationMiddleware` before `SecurityMiddleware`, so HTTPS redirects are assigned the validated request ID, header, and completion log.
- Legacy RAG runtime creation now always assigns a valid UUID (supplied validated request ID when available; generated UUID for non-HTTP callers), persists it on `AgentRun`, invokes a post-creation callback, attaches `request.agent_run_id`, and emits the safe post-creation correlation record.
- All structured JSON emitted by this correlation path use only the approved six fields: `request_id`, `run_id`, `method`, `path`, `status`, and `duration_ms`. The legacy creation record is an HTTP `102` safe record with zero duration; it contains no event name, goals, questions, memory text, or secrets.
- Added `Cache-Control: no-store, private` to authenticated memory exports and an authenticated explicit-memory save form to the ask page.

### Green verification

```text
/home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_accounts.py agent_runtime/tests/test_research_runtime.py -q
```

Result: `36 passed in 2.27s`.

## Re-review fix addendum

### TDD evidence

- Added `test_non_http_research_creation_and_replay_always_persist_valid_request_ids` before changing the runtime boundary. It covers the management-command-style omitted ID path, an invalid supplied value, and replay with omitted/invalid IDs.
- Updated the legacy streaming lifecycle regression to require a separately named lifecycle logger with a JSON payload containing only `request_id` and `run_id`, rather than a synthetic HTTP `102` record.
- Red command:

  ```text
  /home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_research_runtime.py::test_non_http_research_creation_and_replay_always_persist_valid_request_ids agent_runtime/tests/test_research_runtime.py::test_streaming_ask_gets_correlation_header_and_safe_runtime_creation_log -q
  ```

  Result: `2 failed`. `create_research_run()` persisted `NULL` for omitted IDs and rejected invalid IDs; legacy creation telemetry was still an HTTP-logger `102` record.

### Changes and rationale

- Added `normalized_request_id()` at the research-runtime boundary. `create_research_run()` and `replay_research_run()` now always persist a supplied valid UUID or a server-generated UUID, including management-command callers.
- Legacy runtime creation now logs through `zhongbei_info.observability.lifecycle`, separate from HTTP completion telemetry. Its JSON payload is limited to `request_id` and `run_id`; it has no synthetic HTTP status, path, method, duration, event name, or user content. The normal middleware remains the sole HTTP response-status completion log.

### Green verification

```text
/home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_research_runtime.py::test_non_http_research_creation_and_replay_always_persist_valid_request_ids agent_runtime/tests/test_research_runtime.py::test_streaming_ask_gets_correlation_header_and_safe_runtime_creation_log -q
```

Result: `2 passed in 1.84s`.

## Legacy idempotency fix addendum

### TDD evidence

- Added a regression that creates a pre-migration-style `AgentRun` with a matching `client_request_id` and `request_id=NULL`, then reuses it with a valid UUID. The same test verifies a non-null existing ID is never overwritten.
- Red command:

  ```text
  /home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_research_runtime.py::test_idempotent_reuse_backfills_legacy_null_request_id_without_overwriting_existing_id -q
  ```

  Result: `1 failed`; the reused legacy row retained `request_id=None`.

### Change and green verification

- `create_research_run()` now backfills the normalized/generated UUID only when a reused run has `request_id is None`. Existing non-null IDs remain immutable under idempotent retries.
- Green command: the same targeted test passed: `1 passed in 3.36s`.

## Concurrent legacy-backfill fix addendum

### TDD evidence

- Added a race-path regression that simulates a competing retry setting a legacy NULL row's request ID immediately before this retry's conditional update. It asserts the current retry observes the competing immutable ID.
- Red command:

  ```text
  /home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_research_runtime.py::test_legacy_null_request_id_backfill_observes_the_concurrent_winner -q
  ```

  Result: `1 failed`; the prior plain model save did not enter a conditional compare-and-set path.

### Change and green verification

- Replaced the legacy NULL backfill save with `UPDATE ... WHERE request_id IS NULL`, then refreshes the run from the database. Exactly one retry can set the previously NULL value; competing retries read that winner. Existing non-null values remain untouched.
- Green command: the same race-path test passed: `1 passed in 2.40s`.
