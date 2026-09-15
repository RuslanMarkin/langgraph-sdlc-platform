"""Publish the CP-STATUS-001 SDLC handoff as a Langfuse trace."""

from agent_platform.handoff import build_feature_handoff_graph
from agent_platform.observability import flush_langfuse, langfuse_callbacks
from agent_platform.settings import get_settings


def main() -> None:
    """Run the real QA handoff that was created in the CRM repository."""
    settings = get_settings()
    result = build_feature_handoff_graph().invoke(
        {
            "feature_id": "CP-STATUS-001",
            "title": "Статусы контрагентов",
            "analyst_handoff_url": (
                "https://github.com/RuslanMarkin/CRM_Almaz/blob/"
                "7c8376c3006a97f2cb7d2d27880e8e2adb61a96c/"
                "sdlc/handoffs/CP-STATUS-001.json"
            ),
            "development_pr_url": "https://github.com/RuslanMarkin/CRM_Almaz/pull/8",
            "checks_passed": ["pnpm check", "pnpm test", "pnpm build", "GitHub Actions CI"],
            "stage": "ready_for_development",
            "next_executor": "developer",
            "message": "",
        },
        config={
            "callbacks": langfuse_callbacks(settings),
            "configurable": {"thread_id": "CP-STATUS-001"},
            "run_name": "CP-STATUS-001: передача разработки в QA",
            "tags": ["sdlc", "counterparties", "handoff", "qa"],
        },
    )
    flush_langfuse(settings)
    print(result["message"])
    print(f"Langfuse telemetry: {'enabled' if settings.langfuse_enabled else 'disabled'}")


if __name__ == "__main__":
    main()
