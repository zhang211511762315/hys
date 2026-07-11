import json
from typing import Callable

from django.conf import settings

from aggregator.services.ai import finalize_deepseek_budget, release_deepseek_budget, reserve_deepseek_budget

from .schemas import PlanStep, ResearchPlan


DEADLINE_TERMS = ("截止", "报名", "时间", "日程", "安排")
COMPARISON_TERMS = ("比较", "对比", "区别", "哪个", "选择")
PUBLIC_TOOLS = {
    "search_public_content",
    "get_content_details",
    "build_deadline_timeline",
    "compare_evidence",
}


def build_template_plan(goal: str) -> ResearchPlan:
    goal = (goal or "").strip()[:1000]
    if not goal:
        raise ValueError("goal is required")

    steps = [
        PlanStep(
            id="search",
            tool="search_public_content",
            description="检索与目标相关的公开校园信息",
            args={"query": goal, "limit": 8},
        ),
        PlanStep(
            id="details",
            tool="get_content_details",
            description="读取候选信息的可引用详情",
            input_from={"item_ids": "search.item_ids"},
        ),
    ]
    if any(term in goal for term in DEADLINE_TERMS):
        task_type = "deadline_research"
        steps.append(
            PlanStep(
                id="timeline",
                tool="build_deadline_timeline",
                description="提取报名或活动时间并生成时间线",
                input_from={"items": "details.items"},
            )
        )
    elif any(term in goal for term in COMPARISON_TERMS):
        task_type = "comparison"
        steps.append(
            PlanStep(
                id="comparison",
                tool="compare_evidence",
                description="按来源归组并比较候选信息",
                input_from={"items": "details.items"},
            )
        )
    else:
        task_type = "search"

    return ResearchPlan(goal=goal, task_type=task_type, steps=steps)


def build_hybrid_plan(
    goal: str,
    *,
    model_planner: Callable[[str], dict] | None = None,
) -> ResearchPlan:
    fallback = build_template_plan(goal)
    if model_planner is None:
        enabled = getattr(settings, "RESEARCH_AGENT_LLM_PLANNER_ENABLED", False)
        complex_goal = len(goal) >= 40 or sum(goal.count(term) for term in ("并且", "同时", "综合", "分别")) >= 1
        if not enabled or not settings.DEEPSEEK_API_KEY or not complex_goal:
            return fallback
        model_planner = _model_plan
    try:
        plan = ResearchPlan.model_validate(model_planner(goal))
        _validate_model_plan(plan)
        return plan
    except Exception:
        return fallback


def _validate_model_plan(plan: ResearchPlan) -> None:
    seen = set()
    for step in plan.steps:
        if step.tool not in PUBLIC_TOOLS:
            raise ValueError(f"tool is not public: {step.tool}")
        if step.id in seen:
            raise ValueError(f"duplicate step id: {step.id}")
        for path in step.input_from.values():
            dependency = path.split(".", 1)[0]
            if dependency not in seen:
                raise ValueError(f"step references unavailable dependency: {dependency}")
        seen.add(step.id)


def _model_plan(goal: str) -> dict:
    import litellm

    prompt = (
        "你是校园公开信息研究Agent的规划器。只输出JSON，不回答问题。"
        "最多6步，只能使用 search_public_content、get_content_details、"
        "build_deadline_timeline、compare_evidence。写操作和管理员工具禁止使用。"
        "输出字段为 goal、task_type、steps；每个step包含id、tool、description、args、input_from。"
        f"\n用户目标：{goal}"
    )
    max_tokens = 500
    reservation = reserve_deepseek_budget(
        settings.DEEPSEEK_MODEL,
        estimated_prompt_tokens=max(1, len(prompt)),
        estimated_completion_tokens=max_tokens,
    )
    if reservation is None:
        raise RuntimeError("planner budget unavailable")
    finalized = False
    try:
        response = litellm.completion(
            model=f"deepseek/{settings.DEEPSEEK_MODEL}",
            messages=[{"role": "user", "content": prompt}],
            api_key=settings.DEEPSEEK_API_KEY,
            api_base=settings.DEEPSEEK_BASE_URL.rstrip("/"),
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=max_tokens,
            timeout=30,
            drop_params=True,
        )
        payload = response.model_dump() if hasattr(response, "model_dump") else dict(response)
        finalize_deepseek_budget(reservation, payload.get("usage", {}))
        finalized = True
        return json.loads(payload["choices"][0]["message"]["content"])
    finally:
        if not finalized:
            release_deepseek_budget(reservation)
