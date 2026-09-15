from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent_platform.sdlc_agents import (
    AnalysisDraft,
    BusinessRequest,
    DevelopmentPlan,
)
from agent_platform.sdlc_agents import TestPlanDraft as QaTestPlanDraft
from agent_platform.sdlc_workflow import build_sdlc_workflow


class FakeAnalyst:
    def draft(self, request: BusinessRequest, repository_evidence: str) -> AnalysisDraft:
        assert request.feature_id == "CP-STATUS-001"
        assert "counterparties" in repository_evidence
        return AnalysisDraft(
            summary="Добавить статусы.",
            scope=["Поле статуса"],
            non_goals=["Не блокировать договоры"],
            acceptance_criteria=["Статус виден в списке"],
            affected_files=["drizzle/schema.ts"],
            risks_and_questions=[],
        )


class FakeDeveloper:
    def plan(self, analysis: AnalysisDraft) -> DevelopmentPlan:
        return DevelopmentPlan(
            implementation_steps=["Добавить поле"],
            files_to_change=analysis.affected_files,
            migration_plan="Добавить колонку со значением normal.",
            verification_commands=["pnpm test"],
        )


class FakeTestDesigner:
    def plan(self, analysis: AnalysisDraft) -> QaTestPlanDraft:
        return QaTestPlanDraft(
            automated_tests=["Проверить значение по умолчанию"],
            manual_staging_checks=["Проверить миграцию"],
            regression_risks=["Существующие записи"],
        )


def workflow_input(project_root: str) -> dict[str, Any]:
    return {
        "request": {
            "feature_id": "CP-STATUS-001",
            "title": "Статусы контрагентов",
            "description": "Добавить четыре статуса контрагента.",
        },
        "project_root": project_root,
        "evidence_paths": ["example.txt"],
        "stage": "new",
        "audit_trail": [],
    }


def test_human_approvals_gate_parallel_development_and_test_preparation(tmp_path: Any) -> None:
    (tmp_path / "example.txt").write_text("counterparties table", encoding="utf-8")
    graph = build_sdlc_workflow(
        FakeAnalyst(), FakeDeveloper(), FakeTestDesigner(), checkpointer=InMemorySaver()
    )
    config = {"configurable": {"thread_id": "CP-STATUS-001"}}

    first = graph.invoke(workflow_input(str(tmp_path)), config=config)
    assert "__interrupt__" in first
    assert first["__interrupt__"][0].value["gate"] == "analyst_approval"

    second = graph.invoke(
        Command(resume={"decision": "approve", "reviewer": "analyst"}), config=config
    )
    assert "__interrupt__" in second
    assert second["__interrupt__"][0].value["gate"] == "development_and_test_approval"
    assert second["development_plan"]["verification_commands"] == ["pnpm test"]
    assert second["test_plan"]["automated_tests"] == ["Проверить значение по умолчанию"]

    final = graph.invoke(
        Command(resume={"decision": "approve", "reviewer": "qa-lead"}), config=config
    )
    assert final["stage"] == "ready_for_implementation"
    assert final["human_decisions"]["analyst"]["reviewer"] == "analyst"
    assert final["human_decisions"]["plans"]["reviewer"] == "qa-lead"
