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

## MySQL current-read fix addendum

### TDD evidence

- Added a regression that simulates a losing conditional update and asserts that the caller performs a locking `select_for_update()` current read before returning the concurrent winner. This covers the MySQL Repeatable Read stale-snapshot branch rather than relying on a plain refresh.
- Red command:

  ```text
  /home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_research_runtime.py::test_legacy_null_backfill_uses_a_locking_current_read_after_losing_race -q
  ```

  Result: `1 failed`; the previous implementation did not issue a locking current read.

### Change and green verification

- When the atomic NULL-only update loses, `create_research_run()` now reads the row with `select_for_update()` inside its existing transaction. It returns the persisted winner; only if the locked row is still NULL does it write the normalized ID while holding the lock.
- Green command: the same locking-path test passed: `1 passed in 2.30s`.

## Final idempotency fixes addendum

### TDD evidence

- Added a request-level regression for a legacy HTTP idempotency row with `request_id=NULL`; the retry must go through `create_research_run()` and persist the request's validated UUID.
- Added a duplicate-key recovery regression that hides an already committed winner from the initial lookup, injects the duplicate-key failure on the insert attempt, then verifies a locking current read returns that winner. This exercises the first-submission duplicate-recovery path rather than a sequential `get_or_create` hit.
- Red command:

  ```text
  /home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_research_runtime.py::test_research_api_retry_backfills_legacy_null_request_correlation agent_runtime/tests/test_research_runtime.py::test_duplicate_key_recovery_uses_a_locking_current_read_for_the_winner -q
  ```

  Result: `2 failed`; the HTTP endpoint returned before runtime backfill, and the runtime did not attempt insert/duplicate-key recovery.

### Changes

- The HTTP endpoint still uses its preliminary lookup only to preserve quota/concurrency behavior, but always delegates idempotency resolution to `create_research_run()`. Duplicate responses remain `200` and new runs remain `202`.
- `create_research_run()` now performs an initial create in a narrow transaction. On `IntegrityError`, it exits that transaction and uses a fresh locking current read in a new transaction to observe the concurrent winner under MySQL Repeatable Read. Legacy NULL backfill continues through the immutable conditional-update/locking path.

### Green verification

- New regression command: `2 passed in 2.06s`.
- Focused research runtime suite: `/home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_research_runtime.py -q` — `32 passed in 2.25s`.

## HTTP admission serialization fix addendum

### TDD evidence

- Added an authenticated duplicate-admission regression that requires the current user row to be locked before a locking AgentRun lookup and verifies the duplicate skips quota admission.
- Added an authenticated first-admission regression whose quota stub asserts that the user lock and current run lookup occur before quota evaluation, then verifies exactly one new run is created.
- Red command:

  ```text
  /home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_research_runtime.py::test_authenticated_duplicate_admission_locks_user_then_current_run_and_skips_quota agent_runtime/tests/test_research_runtime.py::test_authenticated_first_admission_locks_before_quota_and_creates_once -q
  ```

  Result: `2 failed`; neither lock was held before duplicate/quota handling.

### Change and green verification

- Authenticated research admissions now hold a `select_for_update()` lock on only the calling user's row, then make a locking current lookup for the client request ID, perform quota/concurrency checks only when no run exists, and invoke the runtime authority while the admission lock is held. This serializes same-user first submissions without blocking unrelated users.
- The response semantics remain unchanged: duplicates are `200`, new runs are `202`, and task enqueueing remains after the transaction commits.
- Green command: the two admission regressions passed: `2 passed in 1.96s`.

## Anonymous admission and gap-lock fix addendum

### TDD evidence

- Updated authenticated admission checks to forbid AgentRun absent-key locking while retaining the user-row lock.
- Added an anonymous rejection regression that creates the concurrent winner during quota rejection and requires a fresh post-transaction recheck to return the existing run as `200`.
- Added a different-authenticated-user same-key regression that permits only AgentRun locks by primary key for runtime event sequencing, never a `client_request_id` gap lock.
- Red command:

  ```text
  /home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_research_runtime.py::test_authenticated_duplicate_admission_locks_user_then_current_run_and_skips_quota agent_runtime/tests/test_research_runtime.py::test_authenticated_first_admission_locks_before_quota_and_creates_once agent_runtime/tests/test_research_runtime.py::test_anonymous_rejected_admission_rechecks_and_reuses_a_concurrent_run agent_runtime/tests/test_research_runtime.py::test_different_authenticated_users_same_key_do_not_take_agent_run_gap_locks -q
  ```

  Result: `4 failed`; the HTTP path locked absent AgentRun keys and returned anonymous quota rejection without rechecking for the concurrent winner.

### Changes and green verification

- The HTTP admission path now uses an ordinary client-request existence read; it retains only the authenticated caller's row lock. This avoids inter-user client-key gap locks while the runtime continues to own first-create duplicate recovery.
- Quota/concurrency rejection exits the admission transaction, performs a fresh autocommit existence query, and delegates to the runtime authority only when a matching run now exists. A true rejection with no match still returns `429` and creates nothing.
- New admission regression command: `4 passed in 2.07s`.
- Focused research runtime suite: `36 passed in 2.26s`.

## Durable admission-key mutex addendum

### TDD evidence

- Added regressions for a persistent anonymous admission-key lock before quota evaluation, true quota rejection without run creation, first/duplicate public `202`/`200` semantics for one anonymous key, key-first then user lock ordering for authenticated callers, and independent durable keys for different client request IDs.
- Red command:

  ```text
  /home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_research_runtime.py::test_authenticated_duplicate_admission_locks_user_then_current_run_and_skips_quota agent_runtime/tests/test_research_runtime.py::test_authenticated_first_admission_locks_before_quota_and_creates_once agent_runtime/tests/test_research_runtime.py::test_anonymous_key_lock_rejects_true_quota_without_creating_a_run agent_runtime/tests/test_research_runtime.py::test_anonymous_same_key_admission_lock_preserves_new_and_duplicate_responses agent_runtime/tests/test_research_runtime.py::test_different_authenticated_users_same_key_do_not_take_agent_run_gap_locks -q
  ```

  Result: `5 failed` with `ImportError` for the absent `ResearchAdmissionKey` model.

### Changes and green verification

- Added persistent, globally unique `ResearchAdmissionKey` and migration `0012_researchadmissionkey` after Agent Runtime `0011`.
- The view creates the admission key in a narrow committed transaction; duplicate creation exits the failed transaction and reads the committed key in a fresh transaction. It then locks that key before any AgentRun existence/admission/create action, and locks the authenticated user second. No absent AgentRun key is locked.
- The prior post-rejection recheck was removed. The mutex ensures a same-key anonymous retry waits for the first request's committed create or true rejection, then sees the resulting run or receives the same true `429` without creating a run.
- New regression command: `5 passed in 2.00s`.
- Focused research runtime suite: `37 passed in 2.32s`.

## Admission-key storage bound fix addendum

### TDD evidence

- Updated true-rejection coverage to require deletion of its orphan key.
- Added regressions for repeated rejected unique anonymous IDs, runtime exceptions, retry after a deleted rejected key, and stale-orphan cleanup preserving fresh/active and run-backed keys.
- Red command:

  ```text
  /home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_research_runtime.py::test_anonymous_key_lock_rejects_true_quota_without_creating_a_run agent_runtime/tests/test_research_runtime.py::test_rejected_unique_anonymous_admissions_do_not_accumulate_keys agent_runtime/tests/test_research_runtime.py::test_exception_during_admission_cleans_up_orphan_key agent_runtime/tests/test_research_runtime.py::test_retry_after_true_rejection_recreates_key_and_creates_one_run agent_runtime/tests/test_research_runtime.py::test_stale_orphan_admission_key_cleanup_preserves_active_and_run_backed_keys -q
  ```

  Result: `4 failed`; true rejections and exceptions left admission-key rows, repeated rejected IDs accumulated keys, and stale cleanup did not exist.

### Changes and green verification

- A true quota/concurrency rejection deletes its already locked key only after confirming no AgentRun matches. Active admissions touch `updated_at` while holding the key lock.
- Exceptions call a fresh-transaction orphan cleanup that locks/re-reads the key and deletes it only when no matching run exists. Waiters that received a now-deleted key retry durable key creation before admission.
- Added `cleanup_stale_research_admission_keys()` and integrated it into the existing daily memory cleanup task. It locks/rechecks only keys older than `RESEARCH_ADMISSION_KEY_STALE_SECONDS` (default 300), preserving recent active and run-backed keys.
- New regression command: `5 passed in 1.92s`.
- Focused runtime/account suite: `52 passed in 2.45s`.

## Admission-key deletion/recreation fix addendum

### TDD evidence

- Added a regression that simulates duplicate-key recovery followed by key deletion, then verifies durable creation retries and succeeds.
- Added an exhaustion regression where every create collides and every recovery read is deleted; it requires a sanitized explicit error instead of raw `DoesNotExist`.
- Red command:

  ```text
  /home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_research_runtime.py::test_admission_key_retries_when_duplicate_recovery_row_was_deleted agent_runtime/tests/test_research_runtime.py::test_admission_key_creation_exhaustion_raises_sanitized_error -q
  ```

  Result: `2 failed`; duplicate recovery surfaced `ResearchAdmissionKey.DoesNotExist` directly.

### Change and green verification

- `_get_research_admission_key()` now has a bounded three-attempt create/recover loop. A recovery `DoesNotExist` retries durable creation without sleeping; exhaustion raises only `RuntimeError("research admission key unavailable")`.
- Green command: `2 passed in 1.88s`.

## Admission-key exhaustion response fix addendum

### TDD evidence

- Added a request-level exhaustion regression that forces the admission-key helper unavailable while an orphan exists. It requires generic JSON `503`, preservation of `X-Request-ID`, no internal error text in the body, and race-safe orphan cleanup.
- Red command:

  ```text
  /home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_research_runtime.py::test_admission_key_exhaustion_returns_private_503_and_cleans_orphan -q
  ```

  Result: `1 failed` with missing `ResearchAdmissionUnavailable`; exhaustion was still an unhandled runtime path.

### Change and green verification

- Added `ResearchAdmissionUnavailable`, raised only after the bounded helper exhausts. `research_runs` catches it, invokes fresh locked orphan cleanup, and returns `{ "error": "admission temporarily unavailable" }` with status `503`; correlation middleware continues to add the request-ID header.
- Green command (including direct helper exhaustion): `2 passed in 1.86s`.

## Deleted-before-lock exhaustion fix addendum

### TDD evidence

- Added a request regression that makes both admission-key helper attempts return a key deleted before the view can lock it. It requires generic `503`, a preserved request-ID header, no recreation detail, and no orphan key.
- Red command:

  ```text
  /home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_research_runtime.py::test_deleted_before_lock_admission_key_exhaustion_returns_private_503 -q
  ```

  Result: `1 failed` with raw `RuntimeError("research admission key recreation failed")`.

### Change and green verification

- The exhausted outer key-recreation loop now raises `ResearchAdmissionUnavailable`, so it uses the same fresh orphan cleanup and private JSON `503` handler as helper exhaustion.
- Green command (both exhaustion branches): `2 passed in 1.88s`.
