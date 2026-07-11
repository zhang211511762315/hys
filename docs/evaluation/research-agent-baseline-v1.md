# Research Agent Planner Evaluation — v1

Evaluation date: 2026-07-12

Dataset: `campus-research-v1`

## Scope

This is a deterministic, zero-cost regression evaluation of plan construction and tool permissions. It does not measure retrieval relevance, final-answer correctness, or production latency.

## Dataset

| Category | Cases |
| --- | ---: |
| Retrieval and filtering | 40 |
| Multi-step deadline/comparison tasks | 30 |
| Ambiguous intent | 15 |
| No-answer tasks | 15 |
| Tool failure scenarios | 10 |
| Security and authorization | 10 |
| **Total** | **120** |

## Measured result

| Metric | Result |
| --- | ---: |
| Plan schema validity | 100.0% |
| Expected tool selection accuracy | 100.0% |
| Unauthorized admin-tool selections | 0 |
| Paid model calls | 0 |
| Cost | 0 CNY |

Command:

```bash
python manage.py research_agent_eval --json --settings=zhongbei_info.settings_test
```

## Limits and next experiment

The next report must use a frozen content snapshot with gold document IDs and manually reviewed answer key points. It will compare the legacy single-pass RAG path against the planner/tool workflow and the verifier-enabled workflow using Recall@5, MRR, task completion, citation precision/coverage, P50/P95 latency, token usage, and actual cost. No answer-quality improvement should be claimed from this planner-only report.
