from __future__ import annotations

from typing import Any, Callable, TypedDict

from langgraph.graph import END, StateGraph

from .planner import build_hybrid_plan
from .schemas import ResearchAnswer, ResearchPlan, VerificationResult
from .tools import ToolContext, ToolRegistry, build_default_registry


class ResearchGraphState(TypedDict, total=False):
    goal: str
    actor_is_staff: bool
    plan: dict[str, Any]
    tool_outputs: dict[str, dict[str, Any]]
    executed_tools: list[str]
    answer: dict[str, Any]
    verification: dict[str, Any]
    replan_count: int
    status: str


def _resolve_path(outputs: dict[str, dict[str, Any]], path: str) -> Any:
    step_id, *parts = path.split(".")
    value: Any = outputs[step_id]
    for part in parts:
        value = value[part]
    return value


def build_research_graph(
    registry: ToolRegistry | None = None,
    answer_builder: Callable[[ResearchGraphState, list[dict], dict[str, dict[str, Any]]], dict] | None = None,
    plan_observer: Callable[[ResearchPlan], None] | None = None,
    tool_event_observer: Callable[[Any, Any, dict[str, Any]], None] | None = None,
):
    registry = registry or build_default_registry()

    def plan_node(state: ResearchGraphState) -> ResearchGraphState:
        plan = build_hybrid_plan(state["goal"])
        if plan_observer is not None:
            plan_observer(plan)
        return {**state, "plan": plan.model_dump(mode="json"), "status": "planning"}

    def execute_node(state: ResearchGraphState) -> ResearchGraphState:
        plan = ResearchPlan.model_validate(state["plan"])
        outputs: dict[str, dict[str, Any]] = {}
        executed_tools = []
        context = ToolContext(actor_is_staff=bool(state.get("actor_is_staff")))
        for step in plan.steps:
            payload = dict(step.args)
            for field, path in step.input_from.items():
                payload[field] = _resolve_path(outputs, path)
            spec = registry.get(step.tool)
            outputs[step.id] = registry.execute_with_policy(
                step.tool,
                payload,
                context,
                observer=(
                    (lambda event, current_step=step, current_spec=spec: tool_event_observer(current_step, current_spec, event))
                    if tool_event_observer is not None
                    else None
                ),
            )
            executed_tools.append(step.tool)
        return {
            **state,
            "tool_outputs": outputs,
            "executed_tools": executed_tools,
            "status": "executing",
        }

    def synthesize_node(state: ResearchGraphState) -> ResearchGraphState:
        outputs = state.get("tool_outputs", {})
        details = outputs.get("details", {})
        items = details.get("items") or outputs.get("search", {}).get("items", [])
        if answer_builder is not None and items:
            answer = ResearchAnswer.model_validate(answer_builder(state, items, outputs))
            return {**state, "answer": answer.model_dump(mode="json")}
        if not items:
            answer = ResearchAnswer(
                answer="没有在已发布的公开校园信息中找到足够证据，暂时无法完成该任务。",
                citations=[],
                insufficient_evidence=True,
            )
            return {**state, "answer": answer.model_dump(mode="json")}

        timeline = outputs.get("timeline", {}).get("entries", [])
        if timeline:
            by_id = {item["item_id"]: item for item in items}
            lines = [f"- {entry['title']}：{entry['date_text']}" for entry in timeline]
            cited_ids = {entry["item_id"] for entry in timeline}
            cited_items = [by_id[item_id] for item_id in cited_ids if item_id in by_id]
            answer_text = "根据已发布信息整理出的时间线：\n" + "\n".join(lines)
        else:
            cited_items = items[:5]
            answer_text = "根据已发布信息找到以下结果：\n" + "\n".join(
                f"- {item['title']}：{item['snippet'][:160]}" for item in cited_items
            )
        answer = ResearchAnswer(
            answer=answer_text,
            citations=[
                {
                    "item_id": item["item_id"],
                    "title": item["title"],
                    "source": item["source"],
                    "url": item["url"],
                }
                for item in cited_items
            ],
        )
        return {**state, "answer": answer.model_dump(mode="json")}

    def verify_node(state: ResearchGraphState) -> ResearchGraphState:
        answer = ResearchAnswer.model_validate(state["answer"])
        evidence_ids = {
            item["item_id"]
            for item in state.get("tool_outputs", {}).get("details", {}).get("items", [])
        }
        reasons = []
        if not answer.insufficient_evidence and not answer.citations:
            reasons.append("answer has no citations")
        invalid_ids = {citation.item_id for citation in answer.citations} - evidence_ids
        if invalid_ids:
            reasons.append("answer cites evidence outside tool results")
        verification = VerificationResult(passed=not reasons, reasons=reasons)
        return {**state, "verification": verification.model_dump(mode="json")}

    def replan_node(state: ResearchGraphState) -> ResearchGraphState:
        return {
            **state,
            "replan_count": int(state.get("replan_count", 0)) + 1,
            "status": "planning",
        }

    def route_after_verification(state: ResearchGraphState) -> str:
        if state["verification"]["passed"]:
            return "finalize"
        if int(state.get("replan_count", 0)) < 1:
            return "replan"
        return "finalize"

    def finalize_node(state: ResearchGraphState) -> ResearchGraphState:
        status = "succeeded" if state["verification"]["passed"] else "failed"
        return {**state, "status": status}

    graph = StateGraph(ResearchGraphState)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("verify", verify_node)
    graph.add_node("replan", replan_node)
    graph.add_node("finalize", finalize_node)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "synthesize")
    graph.add_edge("synthesize", "verify")
    graph.add_conditional_edges(
        "verify",
        route_after_verification,
        {"replan": "replan", "finalize": "finalize"},
    )
    graph.add_edge("replan", "synthesize")
    graph.add_edge("finalize", END)
    return graph.compile()
