"""A traceable handoff graph for a feature that has reached QA."""

from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict


class FeatureHandoffState(TypedDict):
    """Minimum immutable context that follows a feature between SDLC roles."""

    feature_id: str
    title: str
    analyst_handoff_url: str
    development_pr_url: str
    checks_passed: list[str]
    stage: str
    next_executor: str
    message: str


def validate_development_evidence(state: FeatureHandoffState) -> FeatureHandoffState:
    """Gate the transfer on the checks that a developer must provide."""
    if not state["checks_passed"]:
        raise ValueError("Нельзя передать задачу в QA без результатов проверок.")
    return {
        **state,
        "message": f"Пакет {state['feature_id']} прошёл gate разработки.",
    }


def prepare_qa_handoff(state: FeatureHandoffState) -> FeatureHandoffState:
    """Create the state which a QA agent or engineer receives next."""
    return {
        **state,
        "stage": "ready_for_qa",
        "next_executor": "qa",
        "message": f"Пакет {state['feature_id']} передан в QA.",
    }


def build_feature_handoff_graph() -> Any:
    """Compile the deterministic analyst → developer → QA transfer graph."""
    builder = StateGraph(FeatureHandoffState)
    builder.add_node("validate_development_evidence", cast(Any, validate_development_evidence))
    builder.add_node("prepare_qa_handoff", cast(Any, prepare_qa_handoff))
    builder.add_edge(START, "validate_development_evidence")
    builder.add_edge("validate_development_evidence", "prepare_qa_handoff")
    builder.add_edge("prepare_qa_handoff", END)
    return builder.compile()
