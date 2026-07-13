# Task 4 — Crawl failure correctness and health-gate remediation

## Scope

- Worktree: `/home/ubuntu/hys/.worktrees/research-agent`
- Starting commit: `f2d87df` (`fix: generate runtime correlation ids consistently`)
- Scope held to the Task 4 brief: safe attachment persistence, durable crawl-failure acknowledgement audit data, explicit operator acknowledgement command, actionable health/dashboard calculations, migration, and tests.
- No deployment, push, production-server action, external re-crawl, acknowledgement of real failures, secret access, or external write was performed.

## Delivered behavior

- Attachment ingest now reads the `Attachment.source_url` field's configured maximum before persistence. An overlong attachment URL is skipped without truncation; the crawl job gets the generic warning `An attachment URL exceeded the supported length and was skipped.` The URL itself is never included in that warning, and the page ingest remains successful.
- `CrawlFailure` now records observed HTTP status plus acknowledgement timestamp, independently confirmed status, and audit note. A database check constraint allows acknowledgement only when the unresolved failure is permanent, the observed and confirmed statuses match, both are HTTP 404 or 410, and a non-empty audit note is recorded.
- A fresh failure observation updates the retained failure record and clears all acknowledgement fields. Failure rows are neither deleted nor hidden: `open_failures` remains the compatibility count of all unresolved rows.
- Added the narrow `acknowledge_crawl_failures` service and `acknowledge_crawl_failures` management command. The command requires one or more `--failure-id`, `--confirmed-status` limited to 404/410, and `--note`; it defaults to dry-run and requires `--apply` to write. It validates all supplied IDs in one transaction before mutating any row, rejects missing/nonexistent/resolved/already-acknowledged/non-HTTP-permanent/transient/network failures, accepts no source-wide option, and reports only IDs plus confirmed status (not failure URLs or error payloads).
- `healthz` now returns `actionable_failures` and `acknowledged_permanent_failures`, while preserving `open_failures` as all unresolved failures. Only actionable failures influence the health gate. The dashboard uses the actionable count for its retry queue and displays the acknowledged permanent count separately; its failure-class breakdown is actionable-only. Internal metrics retain the compatible unresolved gauge and add separate actionable and acknowledged-permanent gauges.
- Added `aggregator` migration `0012_crawlfailure_acknowledgement`, dependent on `aggregator.0010_source_source_group` and the preceding `agent_runtime.0011_agentrun_request_id` migration.

## TDD evidence

Focused tests for oversized attachment skipping, acknowledgement eligibility/refusal/dry-run/apply/reset, command atomic validation, health gate/count compatibility, and dashboard aggregation were added before the new production service/module existed.

Initial command attempted with bare `pytest` could not run because `pytest` was absent from `PATH`; no packages were installed. The repository virtualenv was used instead.

Red command:

```text
/home/ubuntu/hys/.venv/bin/pytest -q aggregator/tests/test_services.py::test_attachment_url_over_model_limit_is_skipped_with_generic_job_warning aggregator/tests/test_services.py::test_acknowledgement_requires_permanent_observed_http_404_or_410_and_resets_on_new_observation aggregator/tests/test_services.py::test_acknowledgement_rejects_transient_network_and_non_http_permanent_failures aggregator/tests/test_services.py::test_acknowledgement_command_validates_all_ids_before_applying_any_change aggregator/tests/test_web.py::test_healthz_gates_only_actionable_failures_and_keeps_open_failure_count_compatible agent_runtime/tests/test_research_runtime.py::test_agent_dashboard_separates_actionable_and_acknowledged_permanent_failures
```

Result: expected collection failure, `ModuleNotFoundError: No module named 'aggregator.services.failures'`.

After the minimal implementation, the same six focused tests passed. The acknowledgement test also verifies previously acknowledged refusal, re-observation reset while retaining one failure row, dry-run non-mutation, command apply mutation, atomic rejection when an eligible ID is mixed with a transient ID, and no URL in command output.

## Verification

- Focused Task 4 tests:

  ```text
  /home/ubuntu/hys/.venv/bin/pytest -q aggregator/tests/test_services.py::test_attachment_url_over_model_limit_is_skipped_with_generic_job_warning aggregator/tests/test_services.py::test_acknowledgement_requires_permanent_observed_http_404_or_410_and_resets_on_new_observation aggregator/tests/test_services.py::test_acknowledgement_rejects_transient_network_and_non_http_permanent_failures aggregator/tests/test_services.py::test_acknowledgement_command_validates_all_ids_before_applying_any_change aggregator/tests/test_web.py::test_healthz_gates_only_actionable_failures_and_keeps_open_failure_count_compatible agent_runtime/tests/test_research_runtime.py::test_agent_dashboard_separates_actionable_and_acknowledged_permanent_failures
  ```

  Result: `6 passed in 2.09s`.

- Focused aggregator/agent-runtime suites:

  ```text
  /home/ubuntu/hys/.venv/bin/pytest -q aggregator/tests/test_services.py aggregator/tests/test_web.py agent_runtime/tests/test_research_runtime.py
  ```

  Result: `83 passed in 3.26s`.

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

- Full suite:

  ```text
  /home/ubuntu/hys/.venv/bin/pytest -q
  ```

  Result: `200 passed in 4.68s`.

- Diff hygiene: `git diff --check` completed without whitespace errors.

## Notes

- Django commands emitted an existing LangGraph pending-deprecation warning. It did not produce a test, check, or migration failure.

## Database-integrity review fix

### Finding and correction

The initial acknowledgement check constraint used `IN` and equality predicates without explicit non-null checks. SQL `CHECK` treats an `UNKNOWN` expression as passing, so an `acknowledged_at` value combined with a null observed or confirmed status could bypass the constraint and be incorrectly excluded from actionable health counts.

The model and unreleased `0012_crawlfailure_acknowledgement` migration now require every acknowledged row to have:

- non-null observed HTTP status in `{404, 410}`;
- non-null independently confirmed status in `{404, 410}`;
- equality between observed and confirmed status;
- a non-null, non-empty audit note; and
- permanent failure class plus `permanent=True`.

Unacknowledged HTTP failures continue to retain their observed `http_status`; only acknowledgement metadata must be absent when `acknowledged_at` is absent.

### TDD evidence

Added a parameterized direct database-write regression test for all incomplete/invalid acknowledgement forms: missing confirmed status, missing observed status, both statuses missing, empty note, status outside 404/410, and mismatched 404/410 statuses. It uses `transaction.atomic()` and expects `IntegrityError`, proving the database rather than only service validation enforces the invariant. The existing service-path test continues to prove a valid observed permanent 404 can be dry-run and applied, then is reset by re-observation.

Red command:

```text
/home/ubuntu/hys/.venv/bin/pytest -q aggregator/tests/test_services.py::test_database_constraint_rejects_every_incomplete_or_invalid_acknowledgement aggregator/tests/test_services.py::test_acknowledgement_requires_permanent_observed_http_404_or_410_and_resets_on_new_observation
```

Result: `3 failed, 4 passed`. The three failures were precisely the NULL-bypass rows: missing confirmed status, missing observed status, and both statuses missing.

After adding explicit `isnull=False` checks plus status membership in both model and migration constraint, the same command returned `7 passed in 1.83s`.

### Verification

- `/home/ubuntu/hys/.venv/bin/pytest -q aggregator/tests/test_services.py aggregator/tests/test_web.py` — `62 passed in 2.89s`.
- `/home/ubuntu/hys/.venv/bin/python manage.py check --settings=zhongbei_info.settings_test` — no issues.
- `/home/ubuntu/hys/.venv/bin/python manage.py makemigrations --check --dry-run --settings=zhongbei_info.settings_test` — no changes detected.
- `git diff --check` — no whitespace errors.
