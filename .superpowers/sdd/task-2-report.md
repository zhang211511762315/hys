# Task 2 — Experimental strategy comparison and promotion gate

## Scope and starting point

- Worktree: `/home/ubuntu/hys/.worktrees/research-agent`
- Starting commit: `2adb3e8` (`docs: record evalops safety fix verification`)
- Scope held to Task 2: deterministic EvalOps strategies, durable paired comparison records, command output, aggregate-only dashboard display, migration, and focused tests. No deployment, production-server action, public research-route strategy selection, registry execution, network call, or external write was performed.

## Delivered behavior

- Added offline-only evaluation strategies in `agent_runtime/evaluation/strategies.py`:
  - `single_agent` delegates only to the existing deterministic template planner.
  - `multi_agent_experimental` records the explicit `planner`, `researcher_evidence_audit`, and `reviewer_safety_expectation_check` stages. The audit records no executed tools, and the reviewer checks public-tool safety plus expected task/tool selection.
- The evaluation runner now persists each strategy stage trace in the immutable `EvaluationCaseResult.detail_json` snapshot.
- Added nullable, indexed `EvaluationRun.comparison_id` and migration `0010_evaluationrun_comparison_id`. Each `run_strategy_comparison()` invocation creates one UUID and records both the baseline and experimental `EvaluationRun` under it.
- Added a deterministic promotion gate. The experimental candidate is eligible only when it has zero unsafe selections, does not regress either plan-valid rate or tool-selection accuracy, costs at most the absolute `5 CNY` cap, and has P95 latency at most `max(1 ms, baseline P95) × multiplier`. The optional `EVAL_PROMOTION_P95_LATENCY_MULTIPLIER` setting defaults to `2.0`.
- Added `research_agent_eval --compare`; comparisons are deliberately durable even without `--record`, so the dashboard has a paired aggregate to display.
- Preserved `DEFAULT_STRATEGY = "single_agent"` and made no public request route accept or expose experimental selection.
- Added an aggregate-only EvalOps comparison card to the Agent dashboard. It reads only paired run metrics and gate status; it neither queries nor renders per-case results, goals, or stage traces. Those remain in Django admin.

## TDD evidence

Each behavior was introduced by a focused failing test before its production implementation:

1. Experimental staged strategy
   - Red: `test_experimental_strategy_is_deterministic_offline_and_traces_audited_stages`
   - Expected failure: `ModuleNotFoundError: agent_runtime.evaluation.strategies`
   - Green: same test passed after adding the strategy module.
2. Durable stage traces
   - Red: `test_recorded_experimental_run_persists_each_case_stage_trace`
   - Expected failure: `ValueError: unsupported evaluation strategy: multi_agent_experimental`
   - Green: same test passed after runner integration and detail snapshot persistence.
3. Promotion gate
   - Red: `test_promotion_gate_requires_safe_quality_cost_and_p95_latency_floor`
   - Expected failure: missing `evaluate_promotion_gate` import.
   - Green: same test passed after the safety, quality, absolute-cost, and 1 ms-floor P95 gate was implemented.
4. Paired comparison records
   - Red: `test_strategy_comparison_records_two_runs_with_one_shared_comparison_id`
   - Expected failure: missing `run_strategy_comparison`.
   - Green: same test passed after adding the UUID field, migration, and paired runner.
5. Command interface
   - Red: `test_eval_command_compare_flag_records_and_returns_the_strategy_comparison`
   - Expected failure: unrecognized `--compare` argument.
   - Green: same test passed after adding the management-command branch.
6. Aggregate-only dashboard
   - Red: `test_agent_dashboard_shows_only_latest_aggregate_evalops_comparison`
   - Expected failure: missing `EvalOps 策略对比` content.
   - Green: same test passed after the aggregate comparison view/context/template implementation.
7. Direct promotion status output
   - Red: paired comparison test failed with missing `promotion_status`.
   - Green: same test passed after exposing the status alongside detailed gate data.
8. Offline-only execution
   - Red: `test_evaluation_strategies_reject_paid_execution` failed because neither strategy raised while paid mode was enabled.
   - Green: both parameterized strategies passed after the runner rejected all non-offline execution before a case can run.

## Verification

- Focused task tests: `/home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_evaluation.py agent_runtime/tests/test_research_runtime.py -q`
  - `32 passed`
- Full agent-runtime suite: `/home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests -q`
  - `88 passed`
- Migration check: `DJANGO_SETTINGS_MODULE=zhongbei_info.settings_test /home/ubuntu/hys/.venv/bin/python manage.py makemigrations --check --dry-run`
  - `No changes detected`
- Django check: `/home/ubuntu/hys/.venv/bin/python manage.py check`
  - `System check identified no issues (0 silenced).`
- Diff hygiene: `git diff --check`
  - no whitespace errors.

## Scope notes

- The new strategy module imports only the template planner and public-tool allowlist; it contains no registry construction, tool execution, network client, persistence, or write call.
- Evaluation persistence is limited to the existing internal EvalOps models, which is required for comparison auditability.
- The public dashboard intentionally omits the comparison UUID and detailed per-case data; Django admin remains the detailed-record surface.
