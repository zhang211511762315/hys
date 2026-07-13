# Task 5 — Operational documentation and delivery report

## Scope and guardrails

- Worktree: `/home/ubuntu/hys/.worktrees/research-agent`
- Scope completed: repository-editable documentation and configuration examples only.
- Explicitly not performed: Docker or Compose invocation, sudo, production access, deployment, push, external CI, backup restore, ACME/certificate commands, paid evaluation, remote embedding calls, or human content review.
- No credentials, certificate material, dumps, tokens, or other secrets were read, written, or included in this report.

## Files changed

- `.env.example`
  - Added the implemented semantic-RAG/embedding setting names with semantic retrieval disabled and blank credential fields.
  - Added the EvalOps offline/paid controls: `EVAL_PAID_ENABLED=0` and `EVAL_PAID_HARD_CAP_CNY=5`.
  - Added session/memory retention and source-health defaults: `RAG_SESSION_RETENTION_DAYS=30`, `MEMORY_RETENTION_DAYS=180`, `SOURCE_FRESHNESS_HOURS=72`, and `SOURCE_OPEN_FAILURE_THRESHOLD=5`.
  - Kept all secret-valued fields blank or as existing non-secret placeholders.
- `docs/deployment/research-agent-runbook.md`
  - Added an explicit four-way status boundary: implemented/local verification; pending privileged server verification; pending deployment/production probes; externally blocked capabilities.
  - Documented EvalOps command syntax, the 200-case `campus-research-v2` limitation, hard paid cap, 2.0 P95 promotion multiplier, and controlled-only experimental strategy.
  - Documented explicit memory retention, cleanup schedule, export/delete/account deletion, and request/run correlation behavior.
  - Documented dry-run-first crawl acknowledgement syntax and required flags, source-health compatibility/actionable counts, loopback metrics restrictions, and overlong attachment-URL behavior.
  - Marked restore proof and ACME staging renewal as pending privileged verification rather than claiming either occurred.
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

### Pending privileged server verification

- Run `deploy/scripts/verify_mysql_restore.sh` against the latest checksum-valid server backup and retain only the safe timestamp/checksum outcome in the server operations log.
- Run an approved staging ACME webroot renewal dry-run that cannot modify the live certificate and record the safe result.

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

`docs/superpowers/plans/2026-07-13-direct-completion.md` now marks the completed, locally reviewed code items in Tasks 1–4 as complete. The Task 4 external re-crawl/acknowledgement remains pending. Task 5 keeps the privileged restore/ACME verification and target-environment Compose, CI, deployment, migration, schedule, and production-probe work unchecked. This documentation-only update does not claim that any server, deployment, certificate, backup, or production probe occurred.
