# Production Agent Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the production safety, RAG quality, evaluation, and experimental multi-Agent gaps without replacing the stable public single-Agent path.

**Architecture:** Preserve Django/Celery/MySQL/Redis/Meilisearch/Nginx. Add authenticated memory and privacy controls, enforce tool execution policy, use Meilisearch user-provided vectors from a remote embedding provider, and isolate multi-Agent execution to evaluation and controlled demonstrations.

**Tech Stack:** Django 5.2, Celery, MySQL, Redis, Meilisearch, Prometheus client, Docker Compose, pytest.

## Global constraints

- Keep anonymous Research Agent requests compatible and stateless beyond a 30-day short session.
- Keep the public single-Agent strategy as the default and never expose experimental multi-Agent mode to anonymous requests.
- Do not add a vector database or local embedding model on the 2C2G server.
- Public LLM spending keeps existing low limits; paid evaluation requires an explicit 5 CNY hard cap.
- Do not print or commit production secrets; rotate production credentials only through server-local configuration.

---

### Task 1: Test isolation and operational documentation

- [ ] Make test settings independent from a production `.env`.
- [ ] Update HTTPS and public-memory documentation to match live behavior.
- [ ] Add regression tests and run the complete check suite.

### Task 2: Authentication, privacy, and memory lifecycle

- [ ] Add username/password registration, login, logout, password change, and account deletion.
- [ ] Add opt-in long-term memory for authenticated users, with 180-day retention, export, and deletion.
- [ ] Add a daily cleanup task for expired anonymous sessions and memory entries.

### Task 3: Tool runtime policy and traces

- [ ] Enforce validation, retry, timeout, error taxonomy, attempt-level persistence, and bounded fallback.
- [ ] Preserve single-Agent API compatibility and emit durable SSE trace events for every attempt.

### Task 4: Hybrid RAG and controlled model evaluation

- [ ] Add remote embedding provider settings and incremental Meilisearch user-provided vector indexing.
- [ ] Add hybrid retrieval with deterministic re-ranking and lexical fallback.
- [ ] Add a 200-case v2 evaluation suite, structured result persistence, and a 5 CNY paid-evaluation guard.

### Task 5: Lightweight observability and source-health gates

- [ ] Add readiness and localhost-only Prometheus metrics endpoints.
- [ ] Add JSON request/run correlation and scheduled external GitHub route/certificate probes.
- [ ] Add source freshness thresholds and actionable health reporting.

### Task 6: Production secret, certificate, and backup operations

- [ ] Add webroot-based ACME renewal and a systemd timer runbook.
- [ ] Add root-only compressed backup, checksum, retention, and temporary-container restore verification scripts.
- [ ] Document and execute staged credential rotation only after safe server-local secret values are supplied.

### Task 7: EvalOps and experimental multi-Agent comparison

- [ ] Add versioned evaluation runs/case results and dashboard reports.
- [ ] Add a bounded Planner/Researcher/Reviewer strategy available only to controlled evaluation.
- [ ] Compare single and multi-Agent performance with promotion gates for quality, cost, and latency.
