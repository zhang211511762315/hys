from __future__ import annotations

from typing import TypedDict


class RagGraphState(TypedDict, total=False):
    question: str
    context_count: int
    answer: str
    cost_cny: str


def build_rag_graph():
    """Build the project RAG graph.

    The streaming HTTP path keeps tight control over token accounting, while this
    graph gives the Agent runtime an explicit LangGraph composition point for
    batch/eval use and resume-safe future expansion.
    """

    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return None

    graph = StateGraph(RagGraphState)

    def retrieve(state: RagGraphState) -> RagGraphState:
        return {**state, "context_count": int(state.get("context_count", 0))}

    def generate(state: RagGraphState) -> RagGraphState:
        return state

    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    return graph.compile()
