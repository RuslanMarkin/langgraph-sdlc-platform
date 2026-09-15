"""Run a local graph invocation and, if configured, publish a Langfuse trace."""

from agent_platform.graph import build_healthcheck_graph
from agent_platform.observability import flush_langfuse, langfuse_callbacks
from agent_platform.settings import get_settings


def main() -> None:
    settings = get_settings()
    graph = build_healthcheck_graph()
    result = graph.invoke(
        {"status": "pending", "message": ""},
        config={
            "callbacks": langfuse_callbacks(settings),
            "configurable": {"thread_id": "infrastructure-smoke-check"},
            "run_name": "infrastructure-smoke-check",
            "tags": ["infrastructure", "smoke-test"],
        },
    )
    flush_langfuse(settings)
    print(result["message"])
    print(f"Langfuse telemetry: {'enabled' if settings.langfuse_enabled else 'disabled'}")


if __name__ == "__main__":
    main()
