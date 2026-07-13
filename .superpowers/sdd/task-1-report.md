# Task 1 — Durable EvalOps v2 baseline report

## Scope and starting point

- Worktree: `/home/ubuntu/hys/.worktrees/research-agent`
- Starting commit: `716716cdf02b6a1a78a182aefcfda2b15d6f008d`
- Scope held to Task 1: durable v2 planner evaluation, persistence, dataset, settings, command, admin, migration, and tests. No Task 2 strategy comparison or production-server work was performed.

## Files changed

- `agent_runtime/models.py` — added `EvaluationRun` and immutable-snapshot `EvaluationCaseResult` models.
- `agent_runtime/migrations/0009_evaluationrun_evaluationcaseresult.py` — creates the two EvalOps tables and the per-run/case uniqueness constraint.
- `agent_runtime/evaluation/runner.py` — added versioned dataset loading, durable optional recording, aggregate plan/tool/safety/latency/cost metrics, paid-mode guardrails, and a backwards-compatible v1 zero-cost wrapper.
- `agent_runtime/evaluation/datasets/campus_research_v2.json` — added the 200-case `campus-research-v2` engineering-reviewed baseline across all required categories.
- `agent_runtime/management/commands/research_agent_eval.py` — added `--dataset`, `--strategy`, `--record`, and structured JSON output; retained a zero-cost v1 command default for compatibility.
- `agent_runtime/admin.py` — registered evaluation runs and per-case results as admin-only records.
- `zhongbei_info/settings.py` — added `EVAL_PAID_ENABLED=False` and `EVAL_PAID_HARD_CAP_CNY=5` defaults.
- `agent_runtime/tests/test_evaluation.py` — added focused EvalOps baseline, recording, paid-guard, command, and admin tests.

## TDD red/green evidence

Red tests were written before each corresponding implementation step:

1. Dataset loader
   - Red: `/home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_evaluation.py::test_campus_research_v2_has_engineering_reviewed_200_case_baseline -q`
   - Output: `ImportError: cannot import name 'load_evaluation_dataset'`
   - Green: same command
   - Output: `1 passed in 0.08s`

2. Durable run/case persistence
   - Red: `/home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_evaluation.py::test_recorded_v2_run_persists_evaluation_and_case_result_snapshots -q`
   - Output: `ImportError: cannot import name 'run_evaluation'`
   - Green: same command
   - Output: `1 passed in 1.82s`

3. Paid-mode defaults and pre-execution cap rejection
   - Red: `/home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_evaluation.py::test_paid_mode_is_disabled_and_over_cap_requests_do_not_execute_cases -q`
   - Output: `AttributeError: 'Settings' object has no attribute 'EVAL_PAID_ENABLED'`
   - Green: same command
   - Output: `1 passed in 0.05s`

4. Management-command flags and JSON record output
   - Red: `/home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_evaluation.py::test_eval_command_accepts_v2_dataset_strategy_record_and_json_output -q`
   - Output: `CommandError: ... unrecognized arguments: --dataset campus-research-v2 --strategy single_agent --record`
   - Green: same command
   - Output: `1 passed in 1.90s`

5. Admin registration
   - Red: `/home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_evaluation.py::test_evaluation_models_are_registered_in_admin -q`
   - Output: assertion failure because `EvaluationRun` was absent from `admin.site._registry`.
   - Green: same command
   - Output: `1 passed in 0.05s`

6. Dataset/planner regression discovered during end-to-end command validation
   - Root cause: three fixture strings accidentally contained the template planner's deadline trigger terms (`安排`, `报名`, and `时间`) while their expected labels were comparison/search.
   - Red: `/home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_evaluation.py::test_campus_research_v2_is_a_deterministic_valid_safe_planner_baseline -q`
   - Output: `assert 0.985 == 1.0`
   - Green: same command after correcting only those fixture terms
   - Output: `1 passed in 0.05s`

## Final verification

- Focused evaluation suite:
  - Command: `/home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests/test_evaluation.py agent_runtime/tests/test_research_evaluation.py -q`
  - Output: `10 passed in 2.76s`
- Full app-level suite:
  - Command: `/home/ubuntu/hys/.venv/bin/python -m pytest agent_runtime/tests -q`
  - Output: `77 passed in 2.88s`
- Migration drift check:
  - Command: `/home/ubuntu/hys/.venv/bin/python manage.py makemigrations --check --dry-run --settings=zhongbei_info.settings_test`
  - Output: `No changes detected`
- Django system check:
  - Command: `/home/ubuntu/hys/.venv/bin/python manage.py check --settings=zhongbei_info.settings_test`
  - Output: `System check identified no issues (0 silenced).`
- Offline v2 command:
  - Command: `/home/ubuntu/hys/.venv/bin/python manage.py research_agent_eval --dataset campus-research-v2 --json --settings=zhongbei_info.settings_test`
  - Output: 200 cases; valid-plan rate `1.0`; tool-selection accuracy `1.0`; unsafe selection count `0`; total cost `0`; no failures.

## Commit

- Focused Task 1 commit: pending final commit hash.

## Self-review and concerns

- `research_agent_eval` intentionally keeps its old zero-cost v1 default to preserve the existing command contract; the durable v2 baseline is selected explicitly with `--dataset campus-research-v2`.
- The only implemented strategy is `single_agent`; Task 2's experimental comparison remains intentionally deferred.
- Paid mode has guardrails but no paid planner execution path was added: it remains disabled by default and all Task 1 evaluation execution is deterministic/offline with zero cost.
- Latency is stored in whole milliseconds. The template planner is sub-millisecond in this environment, so aggregate values can be zero while per-case latency is still measured and persisted at that resolution.
