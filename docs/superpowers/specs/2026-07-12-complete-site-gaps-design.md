# Complete Site Gaps Design

**Date:** 2026-07-12

## Goal

Bring the deployed Zhongbei information site into parity with the verified
`main` implementation, close the highest-risk user-facing and operational
gaps, and leave a reproducible smoke/evaluation trail without inventing paid
model or production-performance results.

## Scope and boundaries

The work covers five bounded areas:

1. deployment parity and durable Agent runtime;
2. security and operational guardrails that do not require guessing secrets;
3. Research Agent browser flow and API error states;
4. data freshness, failure visibility, and sitemap coverage;
5. deployment smoke checks, tests, and documentation.

Historical status at design time: HTTPS was not enabled because the server had
only an IP endpoint. It was subsequently enabled for
`schoolsearchzzychen.online` and `www.schoolsearchzzychen.online` in commit
`e0b5e9a`; certificate renewal and secret rotation remain separate operational
work. Production secrets are never printed or committed, and database volumes
are never removed.

## Architecture

The repository's `main` commit remains the source of truth. The deployment
uses the existing Compose stack with one web process, one general Celery
worker, one dedicated single-concurrency `agent` queue worker, beat, Redis,
MySQL, Meilisearch, and Nginx. The web container applies migrations before
starting; a separate smoke command verifies migration parity, queue presence,
health, and representative public/Agent endpoints.

The public Research Agent remains stateless and rate-limited. Its UI submits a
goal by POST, consumes durable SSE events, can cancel a run, and can replay a
completed run. Run UUIDs are not treated as full authentication; the UI and
docs continue to prohibit private data in public mode.

## Behavior changes

- Add explicit runtime/deployment diagnostics without exposing secret values.
- Make Agent UI failures visible for HTTP 429/5xx, SSE errors, terminal
  cancellation, and reconnect/resume; expose cancel and replay controls.
- Add freshness/failure counts to the dashboard and split sitemap output so
  all public items can be discovered instead of only the first 500.
- Validate invalid date filters as user errors rather than passing `None` into
  ORM comparisons.
- Add regression tests for the deployment mismatch, UI/API contracts, public
  data boundaries, and smoke command output.

## Safety and rollout

Before rebuilding production services, back up MySQL and preserve the current
`.env`. Rebuild only affected services, apply migrations, and verify the web
health check before replacing traffic. The stale one-off test container is
removed only after confirming it is not part of the declared Compose stack;
no named data volume is deleted. If the new web/worker smoke check fails, keep
the previous containers running and report the exact failing gate.

## Acceptance criteria

- Repository tests, Django checks, migration check, Compose validation, and
  zero-cost Agent evaluation pass.
- Live `/research/` returns 200; research create/events/cancel/replay paths are
  reachable; `agent_worker` is running and consumes the `agent` queue.
- No production secret appears in code, logs, or the final report.
- Live health reports data/failure counts, and sitemap coverage is split and
  bounded by standard sitemap limits.
- The report explicitly distinguishes observed facts from unknowns such as
  paid answer quality, P95 latency, and HTTPS availability.
