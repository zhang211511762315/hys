# Task 5 — Operational documentation and delivery report

## Scope and guardrails

- Worktree: `/home/ubuntu/hys/.worktrees/research-agent`
- Scope completed: repository-editable documentation and configuration examples only.
- At the time of the documentation implementation, Docker/Compose, sudo, production access, deployment, push, external CI, backup restore, ACME commands, paid evaluation, remote embedding calls, and human content review had not been performed. The later privileged verification addendum below records the restore and ACME checks completed on 2026-07-14.
- No credentials, certificate material, dump contents, tokens, or other secrets were printed, inspected, copied into the repository, or included in this report. The later restore verification necessarily streamed the compressed archive into its isolated temporary container.

## Files changed

- `.env.example`
  - Added the implemented semantic-RAG/embedding setting names with semantic retrieval disabled and blank credential fields.
  - Added the EvalOps offline/paid controls: `EVAL_PAID_ENABLED=0` and `EVAL_PAID_HARD_CAP_CNY=5`.
  - Added session/memory retention and source-health defaults: `RAG_SESSION_RETENTION_DAYS=30`, `MEMORY_RETENTION_DAYS=180`, `SOURCE_FRESHNESS_HOURS=72`, and `SOURCE_OPEN_FAILURE_THRESHOLD=5`.
  - Kept all secret-valued fields blank or as existing non-secret placeholders.
- `docs/deployment/research-agent-runbook.md`
  - Added explicit status boundaries for implemented/local verification, privileged server verification, pending deployment/production probes, and externally blocked capabilities.
  - Documented EvalOps command syntax, the 200-case `campus-research-v2` limitation, hard paid cap, 2.0 P95 promotion multiplier, and controlled-only experimental strategy.
  - Documented explicit memory retention, cleanup schedule, export/delete/account deletion, and request/run correlation behavior.
  - Documented dry-run-first crawl acknowledgement syntax and required flags, source-health compatibility/actionable counts, loopback metrics restrictions, and overlong attachment-URL behavior.
  - Initially marked restore proof and ACME staging renewal as pending; the 2026-07-14 operational addendum and runbook update now record their successful execution.
- `docs/superpowers/plans/2026-07-12-production-agent-completion.md`
  - Added a dated status note and reconciled completed implementation checkboxes with outstanding deployment, credential, and human-review constraints.

## Local verification evidence

All commands below were run in the repository worktree with `/home/ubuntu/hys/.venv/bin/python` where relevant.

1. Documentation command syntax

   ```text
   /home/ubuntu/hys/.venv/bin/python manage.py acknowledge_crawl_failures --help --settings=zhongbei_info.settings_test
   /home/ubuntu/hys/.venv/bin/python manage.py research_agent_eval --help --settings=zhongbei_info.settings_test
   ```

   Result: both commands exited successfully. The acknowledgement command requires one or more `--failure-id`, `--note`, and `--confirmed-status {404,410}` and describes `--apply` as the write switch; EvalOps accepts `--dataset`, `--strategy`, `--record`, `--compare`, and `--json`.

2. Full local check suite

   ```text
   PYTHON=/home/ubuntu/hys/.venv/bin/python make check
   ```

   Result: `207 passed in 5.32s`; Django system check reported no issues; `makemigrations --check --dry-run` reported `No changes detected`; the default offline v1 evaluation completed with 120 cases, zero cost, and no failures. The existing LangGraph pending-deprecation warning did not cause a failure.

3. Documented v2 offline evaluation command shape

   ```text
   /home/ubuntu/hys/.venv/bin/python manage.py research_agent_eval --dataset campus-research-v2 --strategy single_agent --json --settings=zhongbei_info.settings_test
   ```

   Result: 200 cases across the documented categories; `plan_valid_rate=1.0`, `tool_selection_accuracy=1.0`, `unsafe_tool_selection_count=0`, `total_cost_cny=0`, and no failures. This was non-recording, offline local execution, not a paid run or production measurement.

4. Documentation/config hygiene

   ```text
   git diff --check
   rg --pcre2 -n '^\\[[^]]+\\]\\((?!https?://|#|mailto:)' docs/deployment/research-agent-runbook.md docs/superpowers/plans/2026-07-12-production-agent-completion.md
   ```

   Result: no whitespace errors and no relative Markdown links needing a target check. The environment names added to `.env.example` were checked against `zhongbei_info/settings.py`; `MYSQL_ROOT_PASSWORD` is supplied by `docker-compose.yml` rather than Django settings.

## Operational status after this task

### Implemented and locally verified

- Offline EvalOps v2 dataset/guard behavior, strategy gate contracts, privacy/memory controls, correlation logging contracts, crawl acknowledgement validation, source-health fields, readiness, and internal metrics restrictions are covered by the local suite above.
- The documentation now describes the behavior that is present in source code and distinguishes it from operations that need server access.

### Privileged server verification completed 2026-07-14

- The checksum sidecar for `/var/backups/hys/hys-mysql-20260712T193401Z.sql.gz` verified successfully. The archive was restored into an auto-cleaned temporary MySQL 8.4 container, and the expected `zhongbei_info.aggregator_contentitem` table was verified.
- `certbot renew --dry-run --webroot -w /var/www/certbot` completed successfully against the staging service. The command did not replace the live certificate.

### Pending deployment and production probes

- Validate Compose configuration, run external CI, deploy the reviewed commit, apply migrations, and run public route/readiness/loopback-metrics/scheduler/EvalOps/source-health probes on the target environment.
- Observe the daily `cleanup-expired-agent-memory-daily` Beat task and inspect real source-health counts before applying an acknowledgement.

### Externally blocked capabilities

- Semantic embeddings: needs provider credentials and remote-provider verification.
- Paid evaluation: needs explicit authorization and credentials; default is disabled and the runtime hard cap is 5 CNY.
- Human answer-quality review: needed before any answer-quality or citation-quality claim. `campus-research-v2` is not that benchmark.

## Concern

`EVAL_PROMOTION_P95_LATENCY_MULTIPLIER` is read as a Django setting with a built-in `2.0` default, but `zhongbei_info/settings.py` does not load it from an environment variable. The runbook documents this deliberately and does not add a non-functional `.env.example` entry. If operators need to tune it through `.env`, that requires a separate code/config change and review.

## Follow-up: deployment schedule creation (2026-07-13)

The deployment runbook now requires this pending privileged target-environment step immediately after migrations and before scheduler verification:

```text
docker compose exec -T web python manage.py ensure_crawl_schedules
```

Source verification: `aggregator/management/commands/ensure_crawl_schedules.py` invokes `aggregator.services.scheduling.ensure_fixed_crawl_schedules()` and reports `Ensured fixed crawl schedules.` The service creates or updates the database-backed fixed Celery Beat rows, including `cleanup-expired-agent-memory-daily`; the Compose scheduler does not create those rows by itself. This command was not run against any deployment environment.

## Follow-up: direct-plan completion state (2026-07-13)

At that time, `docs/superpowers/plans/2026-07-13-direct-completion.md` marked the completed, locally reviewed code items in Tasks 1–4 as complete while keeping restore/ACME and target-environment work pending. This historical status was superseded on 2026-07-14 only for the successful restore proof and staging ACME dry-run. Task 4 external re-crawl/acknowledgement plus Compose, CI, deployment, migrations, schedule execution, and production probes remain pending.

## Follow-up: stale admission-key configuration (2026-07-13)

`.env.example` and the deployment runbook now include `RESEARCH_ADMISSION_KEY_STALE_SECONDS=300`. Source verification: `cleanup_stale_research_admission_keys()` considers only keys older than that setting and deletes one only when no `AgentRun` has the same `client_request_id`; AgentRun-backed admission keys are retained. The daily memory-cleanup task invokes this orphan-key cleanup. Focused local verification: `agent_runtime/tests/test_research_runtime.py::test_stale_orphan_admission_key_cleanup_preserves_active_and_run_backed_keys` passed. This is documentation/config coverage only and does not change deployment status or claim the scheduled task has run in production.
