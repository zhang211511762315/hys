# Complete Site Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the live site to parity with the verified Agent implementation, close the highest-risk public/runtime gaps, and verify deployment without exposing or guessing secrets.

**Architecture:** Keep the existing Django/Celery/MySQL/Redis/Meilisearch/Nginx stack. Harden the Research Agent UI around the durable run/event APIs, add bounded sitemap/freshness diagnostics, then rebuild only the Compose services required for the verified commit and run smoke gates.

**Tech Stack:** Django 5.2, Django templates, Celery, Redis, MySQL, Meilisearch, Nginx, pytest, Docker Compose.

## Global Constraints

- Never delete named Docker volumes or database data.
- Never print, commit, or rotate production secrets automatically.
- Keep public research mode stateless and rate-limited until HTTPS/auth is available.
- Do not claim paid answer quality, P95 latency, or HTTPS availability without measurements.
- Every behavior change begins with a failing test and ends with targeted plus full verification.

---

### Task 1: Complete the Research Agent browser flow

**Files:** `agent_runtime/templates/agent_runtime/research.html`, `agent_runtime/views.py`, `agent_runtime/tests/test_research_runtime.py`

- [ ] Add failing tests for Cancel/Replay controls, HTTP 429/5xx messages, SSE error handling, and terminal idempotence.
- [ ] Run `pytest -q agent_runtime/tests/test_research_runtime.py -k 'research_page or cancel or replay'` and confirm red.
- [ ] Add disabled Cancel/Replay controls, active run state, `stream.onerror`, HTTP error handling, and POST calls to existing endpoints. Do not put goals in query strings.
- [ ] Run focused tests and the full suite.
- [ ] Commit as `feat: complete research agent browser controls`.

### Task 2: Complete data freshness and SEO coverage

**Files:** `zhongbei_info/views.py`, `agent_runtime/views.py`, `aggregator/views.py`, `aggregator/tests/test_web.py`, `agent_runtime/tests/test_research_runtime.py`

- [ ] Add failing tests for sitemap index/chunks (maximum 500 URLs per chunk), health freshness fields, and invalid date filters.
- [ ] Confirm the tests fail before implementation.
- [ ] Add `/sitemap-index.xml` and bounded item chunks while preserving `/sitemap.xml` compatibility; expose aggregate freshness/failure fields; validate date input before ORM filters.
- [ ] Run focused tests and `pytest -q`.
- [ ] Commit as `feat: expose freshness and complete sitemap coverage`.

### Task 3: Add deployment smoke and operational gates

**Files:** create `agent_runtime/management/commands/research_agent_smoke.py`; modify `agent_runtime/tests/test_deployment.py`, `Makefile`, `docs/deployment/research-agent-runbook.md`.

- [ ] Add failing tests for missing `replay_of` migration state, missing Agent queue route, and smoke success output.
- [ ] Confirm red with `pytest -q agent_runtime/tests/test_deployment.py -k smoke`.
- [ ] Implement a read-only smoke command that checks migration/model fields, queue routing, and health configuration without printing environment values; add a Make target.
- [ ] Run `make check PYTHON=/home/ubuntu/hys/.venv/bin/python` and Compose validation.
- [ ] Commit as `test: add research agent deployment smoke gate`.

### Task 4: Deploy parity and clean the stale runtime

**Systems:** Docker Compose on `/home/ubuntu/hys`; preserve `.env` and named volumes.

- [ ] Record container/status/resource state and create a single-transaction database backup without echoing credentials.
- [ ] Build/recreate `web worker agent_worker scheduler nginx`, then apply migrations.
- [ ] Verify `agent_worker`, `research_agent_smoke`, `/healthz`, `/research/`, and representative API paths.
- [ ] Confirm `hys-test-web` is not a declared service, then remove only that one stale container and verify port 8001 is closed.
- [ ] Run one bounded public research flow, cancellation, and Replay; inspect recent logs for new tracebacks.

### Task 5: Final verification and handoff

- [ ] Run local tests, Django checks, migration check, Compose validation, and zero-cost evaluation.
- [ ] Run live endpoint matrix and report observed data/failure/freshness metrics.
- [ ] Push verified commits to GitHub `main` and confirm Actions.
- [ ] Explicitly record external prerequisites still unresolved: HTTPS certificate/domain, secret rotation, paid answer quality, P95 latency, and backup restore proof unless measured.

