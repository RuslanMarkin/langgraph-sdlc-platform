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
    feedback_received: str | None = None

    def draft(
        self,
        request: BusinessRequest,
        repository_evidence: str,
        *,
        previous_draft: AnalysisDraft | None = None,
        feedback: str | None = None,
    ) -> AnalysisDraft:
        assert request.feature_id == "CP-STATUS-001"
        assert "counterparties" in repository_evidence
        self.feedback_received = feedback
        return AnalysisDraft(
            summary="Уточнить статусы." if previous_draft else "Добавить статусы.",
            scope=["Поле статуса"],
            non_goals=["Не блокировать договоры"],
            acceptance_criteria=["Статус виден в списке"],
            affected_files=["drizzle/schema.ts"],
            risks_and_questions=[],
        )


class FakeDeveloper:
    feedback_received: str | None = None

    def plan(
        self,
        analysis: AnalysisDraft,
        *,
        previous_plan: DevelopmentPlan | None = None,
        feedback: str | None = None,
    ) -> DevelopmentPlan:
        self.feedback_received = feedback
        return DevelopmentPlan(
            implementation_steps=["Исправить план" if previous_plan else "Добавить поле"],
            files_to_change=analysis.affected_files,
            migration_plan="Добавить колонку со значением normal.",
            verification_commands=["pnpm check" if previous_plan else "pnpm test"],
        )


class FakeTestDesigner:
    feedback_received: str | None = None

    def plan(
        self,
        analysis: AnalysisDraft,
        *,
        previous_plan: QaTestPlanDraft | None = None,
        feedback: str | None = None,
    ) -> QaTestPlanDraft:
        self.feedback_received = feedback
        return QaTestPlanDraft(
            automated_tests=[
                "Повторно проверить значение"
                if previous_plan
                else "Проверить значение по умолчанию"
            ],
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


def test_rejected_analysis_is_revised_with_human_feedback(tmp_path: Any) -> None:
    (tmp_path / "example.txt").write_text("counterparties table", encoding="utf-8")
    analyst = FakeAnalyst()
    graph = build_sdlc_workflow(
        analyst, FakeDeveloper(), FakeTestDesigner(), checkpointer=InMemorySaver()
    )
    config = {"configurable": {"thread_id": "CP-STATUS-001-revision"}}

    first = graph.invoke(workflow_input(str(tmp_path)), config=config)
    assert first["analysis_draft"]["summary"] == "Добавить статусы."

    revised = graph.invoke(
        Command(
            resume={
                "decision": "reject",
                "reviewer": "analyst",
                "feedback": "Уточнить границы первой итерации.",
            }
        ),
        config=config,
    )

    assert "__interrupt__" in revised
    assert revised["__interrupt__"][0].value["gate"] == "analyst_approval"
    assert revised["analysis_draft"]["summary"] == "Уточнить статусы."
    assert analyst.feedback_received == "Уточнить границы первой итерации."
    assert revised["audit_trail"] == [
        "analyst_draft_created",
        "analyst_reject",
        "analyst_draft_created",
    ]


def test_rejected_parallel_plans_are_revised_in_both_branches(tmp_path: Any) -> None:
    (tmp_path / "example.txt").write_text("counterparties table", encoding="utf-8")
    developer = FakeDeveloper()
    test_designer = FakeTestDesigner()
    graph = build_sdlc_workflow(
        FakeAnalyst(), developer, test_designer, checkpointer=InMemorySaver()
    )
    config = {"configurable": {"thread_id": "CP-STATUS-001-plans-revision"}}

    graph.invoke(workflow_input(str(tmp_path)), config=config)
    first_plans = graph.invoke(Command(resume={"decision": "approve"}), config=config)
    assert first_plans["development_plan"]["verification_commands"] == ["pnpm test"]

    revised = graph.invoke(
        Command(
            resume={
                "decision": "reject",
                "reviewer": "Руслан",
                "feedback": "Использовать MySQL и pnpm check.",
            }
        ),
        config=config,
    )

    assert "__interrupt__" in revised
    assert revised["__interrupt__"][0].value["gate"] == "development_and_test_approval"
    assert revised["development_plan"]["verification_commands"] == ["pnpm check"]
    assert revised["test_plan"]["automated_tests"] == ["Повторно проверить значение"]
    assert developer.feedback_received == "Использовать MySQL и pnpm check."
    assert test_designer.feedback_received == "Использовать MySQL и pnpm check."
    assert revised["stage"] == "plans_revision_requested"


def test_workflow_can_start_from_approved_analysis(tmp_path: Any) -> None:
    developer = FakeDeveloper()
    test_designer = FakeTestDesigner()
    graph = build_sdlc_workflow(
        FakeAnalyst(),
        developer,
        test_designer,
        checkpointer=InMemorySaver(),
        entry_stage="parallel",
    )
    state = workflow_input(str(tmp_path))
    state.update(
        {
            "analysis_draft": AnalysisDraft(
                summary="Добавить статусы.",
                scope=["Поле статуса"],
                non_goals=["Не блокировать договоры"],
                acceptance_criteria=["Статус виден в списке"],
                affected_files=["drizzle/schema.ts"],
                risks_and_questions=[],
            ).model_dump(),
            "plans_feedback": "Использовать MySQL и pnpm check.",
            "human_decisions": {"analyst": {"decision": "approve"}},
        }
    )

    result = graph.invoke(state, config={"configurable": {"thread_id": "from-analysis"}})

    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["gate"] == "development_and_test_approval"
    assert developer.feedback_received == "Использовать MySQL и pnpm check."
    assert test_designer.feedback_received == "Использовать MySQL и pnpm check."
