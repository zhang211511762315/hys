# Production Agent Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the production safety, RAG quality, evaluation, and experimental multi-Agent gaps without replacing the stable public single-Agent path.

**Architecture:** Preserve Django/Celery/MySQL/Redis/Meilisearch/Nginx. Add authenticated memory and privacy controls, enforce tool execution policy, use Meilisearch user-provided vectors from a remote embedding provider, and isolate multi-Agent execution to evaluation and controlled demonstrations.

**Tech Stack:** Django 5.2, Celery, MySQL, Redis, Meilisearch, Prometheus client, Docker Compose, pytest.

## Implementation status (2026-07-13)

The direct-completion work implemented and locally verified the offline EvalOps baseline/comparison, memory lifecycle and correlation controls, and crawl acknowledgement/source-health behavior described below. The latest backup restore proof and staging ACME renewal dry-run completed on 2026-07-14. This status does **not** mean the production deployment is complete: CI/deployment, migrations, and target-environment probes remain pending. Embeddings, paid evaluation, and human answer-quality review remain externally blocked by missing credentials, authorization, or reviewers.

`campus-research-v2` is an engineering-reviewed, deterministic 200-case planner baseline, not a human answer-quality benchmark. Paid evaluation remains disabled by default and is capped at 5 CNY; the experimental multi-Agent strategy remains controlled evaluation-only.

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

- [x] Add username/password registration, login, logout, password change, and account deletion. (Implemented; production flow remains to be probed.)
- [x] Add opt-in long-term memory for authenticated users, with 180-day retention, export, and deletion. (Implemented and locally verified; not automatically inserted into prompts.)
- [x] Add a daily cleanup task for expired anonymous sessions and memory entries. (Beat registration is implemented and locally tested; scheduled execution remains a deployment probe.)

### Task 3: Tool runtime policy and traces

- [ ] Enforce validation, retry, timeout, error taxonomy, attempt-level persistence, and bounded fallback.
- [ ] Preserve single-Agent API compatibility and emit durable SSE trace events for every attempt.

### Task 4: Hybrid RAG and controlled model evaluation

- [x] Add remote embedding provider settings and incremental Meilisearch user-provided vector indexing. (Implementation is locally verified; provider credentials and remote indexing verification are externally blocked.)
- [x] Add hybrid retrieval with deterministic re-ranking and lexical fallback. (Lexical fallback remains the production-safe default while semantic retrieval is disabled.)
- [x] Add a 200-case v2 evaluation suite, structured result persistence, and a 5 CNY paid-evaluation guard. (Offline/local verification only; no paid or human answer-quality evaluation has run.)

### Task 5: Lightweight observability and source-health gates

- [x] Add readiness and localhost-only Prometheus metrics endpoints. (Implemented and locally verified; target-host restriction probe remains pending.)
- [x] Add JSON request/run correlation. (Implemented and locally verified; production log/trace inspection remains pending.)
- [ ] Add scheduled external GitHub route/certificate probes.
- [x] Add source freshness thresholds and actionable health reporting. (Implemented and locally verified; real-source review remains pending.)

### Task 6: Production secret, certificate, and backup operations

- [x] Add webroot-based ACME renewal and a systemd timer runbook. (Staging renewal dry-run completed successfully on 2026-07-14 without replacing the live certificate.)
- [x] Add root-only compressed backup, checksum, retention, and temporary-container restore verification scripts. (The latest checksum-valid backup was restored successfully in an auto-cleaned temporary container on 2026-07-14.)
- [ ] Document and execute staged credential rotation only after safe server-local secret values are supplied.

### Task 7: EvalOps and experimental multi-Agent comparison

- [x] Add versioned evaluation runs/case results and dashboard reports. (Offline planner metrics only.)
- [x] Add a bounded Planner/Researcher/Reviewer strategy available only to controlled evaluation.
- [x] Compare single and multi-Agent performance with promotion gates for quality, cost, and latency. (A gate result is not a production-promotion decision.)
