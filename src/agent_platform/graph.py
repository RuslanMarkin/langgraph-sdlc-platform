"""A minimal graph validating the common runtime plumbing.

It is deliberately domain-neutral. Replace or extend its node in a feature branch.
"""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class HealthcheckState(TypedDict):
    status: str
    message: str


def verify_runtime(_: HealthcheckState) -> HealthcheckState:
    """Provide a traceable LangGraph node without calling an LLM."""
    return {
        "status": "ok",
        "message": "LangGraph runtime ready.",
    }


def build_healthcheck_graph() -> Any:
    """Compile the smoke-check graph used in local and CI verification."""
    builder = StateGraph(HealthcheckState)
    builder.add_node("verify_runtime", verify_runtime)
    builder.add_edge(START, "verify_runtime")
    builder.add_edge("verify_runtime", END)
    return builder.compile()
