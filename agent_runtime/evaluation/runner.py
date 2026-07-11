from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from pydantic import BaseModel, Field

from agent_runtime.research.planner import build_template_plan


DATASET_PATH = Path(__file__).parent / "datasets" / "campus_research_v1.json"
RETRIEVAL_FIXTURE_PATH = Path(__file__).parent / "datasets" / "campus_retrieval_v1.json"
UNSAFE_TOOLS = {"retry_source", "reindex_items"}


class ResearchEvalCase(BaseModel):
    id: str
    category: str
    goal: str
    expected_task_type: str
    expected_tools: list[str] = Field(min_length=1)


def load_research_dataset(path: Path = DATASET_PATH) -> list[ResearchEvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    sequence = 1
    for group in payload["groups"]:
        for variant in group["variants"]:
            for topic in variant["topics"]:
                cases.append(
                    ResearchEvalCase(
                        id=f"case-{sequence:03d}",
                        category=group["category"],
                        goal=variant["template"].format(topic=topic),
                        expected_task_type=variant["expected_task_type"],
                        expected_tools=variant["expected_tools"],
                    )
                )
                sequence += 1
    return cases


def run_planner_evaluation(path: Path = DATASET_PATH) -> dict:
    cases = load_research_dataset(path)
    valid = 0
    selected_correctly = 0
    unsafe_count = 0
    failures = []
    for case in cases:
        try:
            plan = build_template_plan(case.goal)
        except Exception as exc:
            failures.append({"id": case.id, "error": str(exc)})
            continue
        valid += int(1 <= len(plan.steps) <= 6)
        tools = [step.tool for step in plan.steps]
        selected_correctly += int(plan.task_type == case.expected_task_type and tools == case.expected_tools)
        unsafe_count += sum(tool in UNSAFE_TOOLS for tool in tools)
        if plan.task_type != case.expected_task_type or tools != case.expected_tools:
            failures.append(
                {
                    "id": case.id,
                    "expected_task_type": case.expected_task_type,
                    "actual_task_type": plan.task_type,
                    "expected_tools": case.expected_tools,
                    "actual_tools": tools,
                }
            )
    total = len(cases)
    return {
        "dataset_version": "campus-research-v1",
        "case_count": total,
        "category_counts": dict(Counter(case.category for case in cases)),
        "plan_valid_rate": round(valid / total, 4) if total else 0,
        "tool_selection_accuracy": round(selected_correctly / total, 4) if total else 0,
        "unsafe_tool_selection_count": unsafe_count,
        "total_cost_cny": "0",
        "failures": failures,
    }


def load_retrieval_fixture(path: Path = RETRIEVAL_FIXTURE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_retrieval_evaluation(queries: list[dict], gold_ids: dict[str, int], registry) -> dict:
    hits = 0
    reciprocal_rank = 0.0
    failures = []
    from agent_runtime.research.tools import ToolContext

    for case in queries:
        result = registry.execute(
            "search_public_content",
            {"query": case["query"], "limit": 5},
            ToolContext(actor_is_staff=False, run_id="offline-eval"),
        )
        item_ids = result["item_ids"]
        gold_id = gold_ids[case["gold_key"]]
        if gold_id in item_ids:
            hits += 1
            reciprocal_rank += 1 / (item_ids.index(gold_id) + 1)
        else:
            failures.append({"id": case["id"], "query": case["query"], "returned_ids": item_ids})
    total = len(queries)
    return {
        "dataset_version": "campus-retrieval-v1",
        "case_count": total,
        "recall_at_5": round(hits / total, 4) if total else 0,
        "mrr": round(reciprocal_rank / total, 4) if total else 0,
        "failures": failures,
    }
