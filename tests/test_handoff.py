from agent_platform.handoff import build_feature_handoff_graph


def test_feature_handoff_moves_to_qa_after_development_gates() -> None:
    result = build_feature_handoff_graph().invoke(
        {
            "feature_id": "CP-STATUS-001",
            "title": "Статусы контрагентов",
            "analyst_handoff_url": "https://example.test/handoff.json",
            "development_pr_url": "https://example.test/pull/8",
            "checks_passed": ["pnpm test"],
            "stage": "ready_for_development",
            "next_executor": "developer",
            "message": "",
        },
        config={"configurable": {"thread_id": "test-handoff"}},
    )

    assert result["stage"] == "ready_for_qa"
    assert result["next_executor"] == "qa"
    assert result["message"] == "Пакет CP-STATUS-001 передан в QA."
