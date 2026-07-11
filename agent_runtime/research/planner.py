from .schemas import PlanStep, ResearchPlan


DEADLINE_TERMS = ("截止", "报名", "时间", "日程", "安排")
COMPARISON_TERMS = ("比较", "对比", "区别", "哪个", "选择")


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
