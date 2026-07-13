# Direct Production-Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete every production-agent gap that can be implemented and verified without new third-party credentials or a claim of human domain review.

**Architecture:** Preserve the public single-Agent research route. Add a persistent offline EvalOps layer around the existing planner, isolate Planner/Researcher/Reviewer execution to evaluation, complete account-memory operations and correlation logging, and make crawl-health acknowledgements explicit rather than hiding known permanent failures.

**Tech Stack:** Django 5.2, Celery Beat, MySQL, Redis, LangGraph, Meilisearch, pytest, Docker Compose.

## Global Constraints

- The public Research Agent remains single-Agent and does not expose experimental strategy selection.
- `campus-research-v2` has exactly 200 deterministic planner cases and is labelled an engineering-reviewed baseline, never a human-reviewed answer-quality benchmark.
- Offline evaluation makes no paid model calls; any future paid run is hard-capped at 5 CNY and disabled by default.
- Do not add or print third-party secrets, enable semantic embeddings, or rotate credentials.
- Acknowledging a failure is limited to independently confirmed permanent 404/410 failures; transient and network failures remain actionable.
- All new behavior is implemented test-first and deployed only after the complete test suite, Django checks, migration check, Compose validation, and targeted production probes pass.

---

### Task 1: Durable EvalOps v2 baseline

**Files:** `agent_runtime/models.py`, new migration, `agent_runtime/evaluation/runner.py`, `agent_runtime/evaluation/datasets/campus_research_v2.json`, `agent_runtime/management/commands/research_agent_eval.py`, `agent_runtime/tests/test_evaluation.py`, `agent_runtime/admin.py`.

- [ ] Add `EvaluationRun` linked one-to-one to its `AgentRun`, recording dataset version, strategy, mode, budget cap, status, metrics, timestamps, and error text.
- [ ] Add `EvaluationCaseResult` linked to an evaluation run, recording the immutable expected/actual planning fields, status, latency, cost, and structured detail for one case.
- [ ] Add exactly 200 versioned `campus-research-v2` cases across normal, multi-step, ambiguous, no-answer, tool-failure, security, and multi-constraint categories; mark the dataset metadata as `engineering-reviewed-baseline`.
- [ ] Make the runner persist one evaluation run and one result per case, calculate valid-plan/tool-selection/unsafe-tool/latency/cost metrics, and keep the v1 function as a compatible zero-cost wrapper.
- [ ] Add `EVAL_PAID_ENABLED=False` and `EVAL_PAID_HARD_CAP_CNY=5`; reject paid mode unless explicitly enabled and reject any requested cap above 5 CNY before a case executes.
- [ ] Extend the command with `--dataset`, `--strategy`, `--record`, and JSON output while retaining a zero-cost default.

### Task 2: Experimental strategy comparison and promotion gate

**Files:** new `agent_runtime/evaluation/strategies.py`, `agent_runtime/evaluation/runner.py`, `agent_runtime/views.py`, `agent_runtime/templates/agent_runtime/agent_dashboard.html`, `agent_runtime/tests/test_evaluation.py`, `agent_runtime/tests/test_research_runtime.py`.

- [ ] Implement a `single_agent` strategy using the existing template planner and a `multi_agent_experimental` strategy with separate Planner, Researcher evidence audit, and Reviewer safety/expectation check stages.
- [ ] Keep both strategies deterministic and offline; the multi-Agent strategy may not call public tools, make external writes, or become selectable from public requests.
- [ ] Add comparison output and promotion status: multi-Agent can only be a candidate if it has no unsafe selection, no lower plan-valid/tool-selection score, no higher cost than the 5 CNY cap, and latency within the configured multiplier of single-Agent.
- [ ] Show only aggregate latest EvalOps comparison data on the Agent dashboard; detailed per-case data remains admin-only.

### Task 3: Memory lifecycle, account operations, and correlation logs

**Files:** `aggregator/services/scheduling.py`, `aggregator/tests/test_schedule.py`, `zhongbei_info/observability.py`, `zhongbei_info/settings.py`, `zhongbei_info/urls.py` or middleware configuration, `agent_runtime/models.py`, migration, `agent_runtime/research/runtime.py`, `agent_runtime/views.py`, `agent_runtime/templates/agent_runtime/ask.html`, `agent_runtime/templates/agent_runtime/account_privacy.html`, `agent_runtime/urls.py`, `agent_runtime/tests/test_accounts.py`, `agent_runtime/tests/test_research_runtime.py`.

- [ ] Register a daily `agent_runtime.tasks.cleanup_expired_memory_task` Beat schedule idempotently alongside existing crawl schedules.
- [ ] Add explicit authenticated memory save, JSON export download, and form-based deletion in the account UI; the API remains backward compatible and only ever returns the caller's data.
- [ ] Persist a server-validated correlation ID on each research `AgentRun`, return `X-Request-ID` on every HTTP response, and emit JSON records containing only request/run IDs, method, path, status, and duration (never goals, memory text, passwords, or secrets).
- [ ] Keep anonymous short-lived sessions unchanged and do not insert long-term memory automatically into prompts.

### Task 4: Crawl failure correctness and health-gate remediation

**Files:** `aggregator/models.py`, migration, `aggregator/services/pipeline.py`, new `aggregator/services/failures.py`, new `aggregator/management/commands/acknowledge_crawl_failures.py`, `agent_runtime/views.py`, `agent_runtime/templates/agent_runtime/agent_dashboard.html`, `aggregator/tests/test_services.py`, `aggregator/tests/test_web.py`, `agent_runtime/tests/test_research_runtime.py`.

- [ ] Skip overlong attachment URLs with a crawl-job warning instead of failing an otherwise valid page; never truncate a URL into a different resource.
- [ ] Add explicit acknowledgement metadata only for permanent failures. A newly observed failure clears a prior acknowledgement.
- [ ] Calculate health gates from actionable unresolved failures and expose acknowledged permanent counts separately.
- [ ] Provide a dry-run-first operator command that can acknowledge only specified permanent failures with an audit note; it must not suppress network or transient failures.
- [ ] After deployment, re-crawl the now-reachable official and employment sources, then acknowledge only the externally rechecked 404 records for the education and continuing-education sources.

### Task 5: Operational verification and delivery

**Files:** `docs/deployment/research-agent-runbook.md`, `.env.example`, `docs/superpowers/plans/2026-07-12-production-agent-completion.md`.

- [ ] Document all new environment defaults, operational commands, dataset limitations, and the distinction between implementation, deployment, and verification.
- [ ] Execute a temporary-container restore verification using the latest checksum-valid backup, and run a staging ACME renewal dry-run without modifying the live certificate.
- [ ] Run full tests, checks, migration checks, Compose configuration validation, CI, deploy only the reviewed commit, apply migrations, and verify public routes, readiness, metrics restriction, scheduled cleanup, EvalOps command, and source-health state.
