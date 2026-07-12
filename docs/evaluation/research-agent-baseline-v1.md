# Research Agent Planner Evaluation — v1

Evaluation date: 2026-07-12

Dataset: `campus-research-v1`

## Scope

This report contains deterministic, zero-cost regression gates for plan construction, tool permissions, and frozen-corpus retrieval. It does not measure final-answer correctness or production latency.

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

The frozen retrieval fixture contains 20 synthetic public documents and 40 gold queries. CI requires Recall@5 ≥ 95% and MRR ≥ 90%. The gate is implemented in `test_frozen_corpus_retrieval_meets_recall_and_mrr_gate`; this report does not invent a more precise measured value.

Command:

```bash
python manage.py research_agent_eval --json --settings=zhongbei_info.settings_test
```

## Limits and next experiment

The next paid experiment must add manually reviewed answer key points and compare the legacy single-pass RAG path against planner/tool and verifier-enabled variants. It must report task completion, citation precision/coverage, P50/P95 latency, token usage, actual cost and failure categories. No answer-quality improvement is claimed here.
