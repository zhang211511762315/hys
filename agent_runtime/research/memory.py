from django.conf import settings

from agent_runtime.models import RagSession


FOLLOW_UP_TERMS = ("这些", "它们", "上述", "刚才", "继续", "其中")


def resolve_goal_with_memory(goal: str, session: RagSession | None) -> str:
    goal = (goal or "").strip()[:1000]
    if not getattr(settings, "RESEARCH_AGENT_SESSION_MEMORY_ENABLED", False) or session is None:
        return goal
    if not any(term in goal for term in FOLLOW_UP_TERMS):
        return goal
    history = list(session.messages.order_by("-created_at")[:4])
    history.reverse()
    if not history:
        return goal
    context = "\n".join(f"{message.get_role_display()}：{message.content[:500]}" for message in history)
    return f"会话上下文：\n{context}\n当前目标：{goal}"
