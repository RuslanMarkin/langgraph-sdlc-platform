from agent_platform.graph import build_healthcheck_graph


def test_healthcheck_graph_completes() -> None:
    result = build_healthcheck_graph().invoke(
        {"status": "pending", "message": ""},
        config={"configurable": {"thread_id": "test-thread"}},
    )

    assert result["status"] == "ok"
    assert result["message"] == "LangGraph runtime ready (thread_id=test-thread)."
