"""A minimal graph validating the common runtime plumbing.

It is deliberately domain-neutral. Replace or extend its node in a feature branch.
"""

from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph


class HealthcheckState(TypedDict):
    status: str
    message: str


def verify_runtime(_: HealthcheckState, config: RunnableConfig) -> HealthcheckState:
    """Provide a traceable LangGraph node without calling an LLM."""
    thread_id = config.get("configurable", {}).get("thread_id", "unknown")
    return {
        "status": "ok",
        "message": f"LangGraph runtime ready (thread_id={thread_id}).",
    }


def build_healthcheck_graph():
    """Compile the smoke-check graph used in local and CI verification."""
    builder = StateGraph(HealthcheckState)
    builder.add_node("verify_runtime", verify_runtime)
    builder.add_edge(START, "verify_runtime")
    builder.add_edge("verify_runtime", END)
    return builder.compile()
