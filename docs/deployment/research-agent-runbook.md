# Research Agent deployment runbook

## Scope and verification status

This runbook distinguishes repository implementation from server operations.

- **Implemented and locally verified:** the offline EvalOps baseline and comparison gate, opt-in memory lifecycle and account privacy controls, request/run correlation, crawl-failure acknowledgement rules, source-health fields, readiness, and loopback-only metrics. Local tests cover their contracts; this is not evidence of production availability or performance.
- **Pending privileged server verification:** restore a checksum-valid backup in the temporary container and perform a staging ACME renewal dry-run. These require the server backup location, Docker access, and certificate/webroot state; neither has been run from this repository task.
- **Pending deployment and production probes:** Compose validation, CI, deployment of the reviewed commit, migrations, public-route/readiness/metrics checks, Beat cleanup observation, the EvalOps command, and source-health review must be run on the target environment and recorded there.
- **Externally blocked:** semantic embeddings require separately supplied provider credentials; paid evaluation requires explicit authorization and credentials; human review is required before making any answer-quality claim. None of these capabilities is enabled by the defaults below.

## Preflight

1. Copy `.env.example` to `.env`, replace placeholder secrets, and set the production domain in `DJANGO_ALLOWED_HOSTS`, `PUBLIC_SITE_BASE_URL`, and `CSRF_TRUSTED_ORIGINS`.
2. Run `make check` with the project virtual environment.
3. Run `APP_ENV_FILE=.env docker compose config --quiet`.
4. Back up MySQL and `.env` before migrations.

### Research Agent defaults

Keep the following defaults unless an approved change has been reviewed:

- `RAG_SEMANTIC_ENABLED=0`; hybrid semantic retrieval requires all of `EMBEDDING_BASE_URL`, `EMBEDDING_API_KEY`, and `EMBEDDING_MODEL`. Without those credentials, retrieval remains lexical. `RAG_SEMANTIC_RATIO=0.35`, `RAG_EMBEDDER_NAME=campus-multilingual-v1`, and `EMBEDDING_TIMEOUT_SECONDS=15` describe the implemented settings but do not enable a provider.
- EvalOps is offline and zero-cost by default: `EVAL_PAID_ENABLED=0` and `EVAL_PAID_HARD_CAP_CNY=5`. The runtime clamps the effective paid cap to 5 CNY even if an environment value is higher. The promotion gate uses the source default `EVAL_PROMOTION_P95_LATENCY_MULTIPLIER=2.0`: a candidate P95 may not exceed twice the baseline P95. This is currently a Django setting lookup with a built-in default, not an environment variable accepted by `.env`.
- Anonymous RAG sessions use `RAG_SESSION_RETENTION_DAYS=30`. Authenticated long-term memory is created only by an explicit save and uses `MEMORY_RETENTION_DAYS=180`. `RESEARCH_ADMISSION_KEY_STALE_SECONDS=300` controls cleanup of old orphan request-admission keys only; a key with a matching `AgentRun` is never deleted by this cleanup. The scheduled `agent_runtime.tasks.cleanup_expired_memory_task` runs daily at 03:00 in `TIME_ZONE` after the scheduler has registered its Beat entry.
- Source health uses `SOURCE_FRESHNESS_HOURS=72` and `SOURCE_OPEN_FAILURE_THRESHOLD=5`. A source-health alert is raised for no successful crawl within the freshness window or for more than the configured number of actionable unresolved failures.

Do not put provider credentials, production tokens, database dumps, or certificate keys in `.env.example`, Git, command output, or an evaluation report.

## EvalOps and dataset limits

`campus-research-v2` contains exactly 200 deterministic engineering-reviewed planner cases spanning normal, multi-step, ambiguous, no-answer, tool-failure, security, and multi-constraint situations. It measures planner validity, tool selection, unsafe selections, latency, and cost. It is **not** a human-reviewed answer-quality benchmark and cannot justify an answer-quality, citation-quality, or production-latency claim.

Run the durable offline baseline after migrations on the target environment:

```bash
docker compose exec -T web python manage.py research_agent_eval \
  --dataset campus-research-v2 --strategy single_agent --record --json
```

Run the offline controlled comparison (it records both strategies and returns the promotion gate):

```bash
docker compose exec -T web python manage.py research_agent_eval \
  --dataset campus-research-v2 --compare --json
```

The public Research Agent remains single-Agent. `multi_agent_experimental` is evaluation-only, deterministic, and may not be selected by public requests. A `candidate` comparison status only means its recorded aggregate metrics passed the deterministic safety gate; it is not a production-promotion authorization. The command has no paid-mode flag. Treat paid evaluation as externally blocked until separately authorized and supplied credentials are available.

## Privacy, retention, and correlation

Authenticated users can explicitly save long-term memory from the account privacy page, export only their own memory at `/account/memory-export/`, delete individual entries, or delete their account at `/account/delete/`. The memory API is authenticated and scoped to the caller (`GET`/`POST /api/v1/memory`, `DELETE /api/v1/memory/<uuid>`). Long-term memory is never added to prompts automatically. The export is a JSON attachment with `Cache-Control: no-store, private`.

Every HTTP response returns `X-Request-ID`. A supplied value is accepted only when it is a valid UUID; otherwise the server generates one. Research runs persist the validated correlation ID. Completion logs are JSON restricted to request ID, run ID, method, path, status, and duration; do not add goals, memory text, passwords, tokens, or secrets to those logs.

## Crawl acknowledgement and source health

An acknowledgement is an audited operator statement, not deletion or suppression of a failure. It applies only to explicitly named, unresolved, independently confirmed permanent HTTP 404 or 410 failures whose observed status matches `--confirmed-status`. Network, transient, non-HTTP, resolved, missing, and already acknowledged failures are rejected. All requested IDs are validated before any write, and a new observation clears a previous acknowledgement.

Always begin with the default dry run (omit `--apply`):

```bash
docker compose exec -T web python manage.py acknowledge_crawl_failures \
  --failure-id 123 --confirmed-status 404 \
  --note "Confirmed against the official source on YYYY-MM-DD"
```

Only after an external recheck and review, repeat the exact command with `--apply`:

```bash
docker compose exec -T web python manage.py acknowledge_crawl_failures \
  --failure-id 123 --confirmed-status 404 \
  --note "Confirmed against the official source on YYYY-MM-DD" --apply
```

Repeat `--failure-id` for each separately reviewed row. The command requires every shown flag; it has no source-wide acknowledgement option and does not print URLs or error payloads.

`/healthz` retains `open_failures` as the compatibility count of all unresolved failures. It separately exposes `actionable_failures` (unresolved and unacknowledged) and `acknowledged_permanent_failures`. Only actionable failures affect `source_health_ok` and `source_health_alerts`; an acknowledged permanent failure remains in `open_failures`. `/internal/metrics` exposes corresponding gauges but is restricted by Nginx to loopback and by the Django view to loopback or the internal proxy header. Verify that restriction from the target host; do not publish this endpoint.

If an attachment URL exceeds the configured model field length, crawling skips that attachment and records the generic job warning `An attachment URL exceeded the supported length and was skipped.` The URL is not truncated into a different resource, and an otherwise valid page can still complete.

For the production HTTPS deployment, place the Let's Encrypt material at
`/etc/letsencrypt/live/schoolsearchzzychen.online/` and allow inbound TCP 80
and 443 in the cloud security group. Port 80 intentionally redirects to HTTPS.

## Deploy

**Pending privileged target-environment deployment sequence (not run by this repository task):**

```bash
docker compose build web worker agent_worker scheduler
docker compose up -d mysql redis meilisearch
docker compose up -d web worker agent_worker scheduler nginx
docker compose exec web python manage.py migrate --noinput
docker compose exec -T web python manage.py ensure_crawl_schedules
docker compose exec web python manage.py research_agent_eval --dataset campus-research-v2 --strategy single_agent --record --json
```

`ensure_crawl_schedules` creates or updates the fixed Celery Beat rows, including
`cleanup-expired-agent-memory-daily`. Run it after migrations on a fresh deployment
and before verifying scheduler registration; starting the Compose scheduler alone
does not create these database-backed Beat rows.

The Nginx service publishes both ports, serves the ACME webroot, and mounts
`/etc/letsencrypt` read-only. Install the committed systemd unit and timer once:

```bash
sudo cp deploy/systemd/hys-certbot-renew.service /etc/systemd/system/
sudo cp deploy/systemd/hys-certbot-renew.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hys-certbot-renew.timer
```

The timer checks daily and runs `certbot renew --webroot`, then reloads Nginx
without stopping HTTPS traffic. Verify it with `systemctl list-timers
hys-certbot-renew.timer`.

## Backups and restore proof

Run `sudo deploy/scripts/backup_mysql.sh` daily from a root-owned timer; it
writes compressed, checksummed backups to `/var/backups/hys` and keeps seven
days by default. Validate a backup without touching production data with:

```bash
sudo deploy/scripts/verify_mysql_restore.sh /var/backups/hys/hys-mysql-<timestamp>.sql.gz
```

The restore script creates a temporary isolated MySQL container and volume,
checks the checksum and required tables, then removes only its own resources.
This command is a **pending privileged server verification**, not a verification
performed by this repository task. Record the archive timestamp and checksum
result in the server operations log after it succeeds; never include dump
contents or credentials in that record.

The corresponding ACME staging dry run is also pending privileged server
verification. Use the server-approved staging command and webroot only after
confirming it cannot modify the live certificate; record the resulting exit
status and renewal output in server operations. Do not treat installation of
the service or timer as proof that renewal works.

Install `deploy/systemd/hys-backup.service` and `deploy/systemd/hys-backup.timer`
with the same `systemctl daemon-reload` and `enable --now` flow as certificate
renewal.

After deployment, verify `docker compose ps`, `/healthz`, `/readyz`, one research run, its SSE trace and a Replay. Confirm only `agent_worker` consumes the `agent` queue. After `ensure_crawl_schedules`, confirm the scheduler has registered `cleanup-expired-agent-memory-daily`, then observe one successful scheduled cleanup. Check `/internal/metrics` locally and confirm a non-loopback request is denied. Review `/healthz` counts and alerts before acknowledging any failure.

The read-only deployment gate is:

```bash
docker compose exec -T web python manage.py research_agent_smoke --json
```

It checks the replay migration, Agent queue route, and positive quota/concurrency settings without printing secrets or calling a model provider.

## Rollback and incidents

Keep the previous image/config and restore them with `docker compose up -d`. Treat schema rollback as a separately reviewed operation; restore the database backup if a migration is not backward compatible. If Redis is unavailable, new async work pauses but MySQL traces remain. If the model is unavailable or the budget is exhausted, deterministic retrieval fallback remains. Repair actions should pass through `AgentApproval`, never public write tools.

Do not claim production P95, availability, paid answer accuracy, human-reviewed answer quality, certificate renewal, backup restore proof, or 7-day stability until those measurements have actually run. Record model/prompt versions, dataset version and limitations, case count, token/cost totals, failure categories, and the distinction between local implementation evidence and target-environment probes in each report.
