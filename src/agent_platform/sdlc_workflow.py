"""Human-gated LangGraph workflow with parallel development and test preparation."""

from operator import add
from typing import Annotated, Any, Literal, cast

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt
from typing_extensions import TypedDict

from agent_platform.sdlc_agents import (
    AnalysisDraft,
    AnalystAgent,
    BusinessRequest,
    DeveloperPlannerAgent,
    DevelopmentPlan,
    TestDesignerAgent,
    TestPlanDraft,
    _read_repository_evidence,
)


class SdlcState(TypedDict, total=False):
    """Persisted state; all artifacts are structured and versionable."""

    request: dict[str, Any]
    project_root: str
    evidence_paths: list[str]
    analysis_draft: dict[str, Any]
    analysis_feedback: str
    plans_feedback: str
    development_plan: dict[str, Any]
    test_plan: dict[str, Any]
    stage: str
    human_decisions: dict[str, Any]
    audit_trail: Annotated[list[str], add]


def _approved(decision: dict[str, Any]) -> bool:
    return decision.get("decision") == "approve"


def build_sdlc_workflow(
    analyst: AnalystAgent,
    developer: DeveloperPlannerAgent,
    test_designer: TestDesignerAgent,
    *,
    checkpointer: Any,
    entry_stage: Literal["analysis", "parallel"] = "analysis",
) -> Any:
    """Build a workflow where no role can advance without human confirmation."""

    def draft_analysis(state: SdlcState) -> SdlcState:
        request = BusinessRequest.model_validate(state["request"])
        evidence = _read_repository_evidence(state["project_root"], state["evidence_paths"])
        previous_draft = None
        if state.get("analysis_draft"):
            previous_draft = AnalysisDraft.model_validate(state["analysis_draft"])
        draft = analyst.draft(
            request,
            evidence,
            previous_draft=previous_draft,
            feedback=state.get("analysis_feedback"),
        )
        return {
            "analysis_draft": draft.model_dump(),
            "stage": "awaiting_analyst_approval",
            "audit_trail": ["analyst_draft_created"],
        }

    def approve_analysis(state: SdlcState) -> SdlcState:
        decision = cast(
            dict[str, Any],
            interrupt(
                {
                    "gate": "analyst_approval",
                    "artifact": state["analysis_draft"],
                    "allowed_decisions": ["approve", "reject"],
                }
            ),
        )
        result: SdlcState = {
            "human_decisions": {"analyst": decision},
            "stage": "analysis_approved" if _approved(decision) else "analysis_revision_requested",
            "audit_trail": [f"analyst_{decision.get('decision', 'invalid')}"],
        }
        if not _approved(decision):
            result["analysis_feedback"] = str(decision.get("feedback", ""))
        return result

    def route_after_analysis(state: SdlcState) -> list[Send] | Literal["draft_analysis"]:
        decision = state["human_decisions"]["analyst"]
        if not _approved(decision):
            return "draft_analysis"
        return [
            Send("prepare_development_plan", state),
            Send("prepare_test_plan", state),
        ]

    def prepare_development_plan(state: SdlcState) -> SdlcState:
        analysis = AnalysisDraft.model_validate(state["analysis_draft"])
        previous_plan = None
        if state.get("development_plan"):
            previous_plan = DevelopmentPlan.model_validate(state["development_plan"])
        plan = developer.plan(
            analysis,
            previous_plan=previous_plan,
            feedback=state.get("plans_feedback"),
        )
        return {
            "development_plan": plan.model_dump(),
            "audit_trail": ["development_plan_created"],
        }

    def prepare_test_plan(state: SdlcState) -> SdlcState:
        analysis = AnalysisDraft.model_validate(state["analysis_draft"])
        previous_plan = None
        if state.get("test_plan"):
            previous_plan = TestPlanDraft.model_validate(state["test_plan"])
        plan = test_designer.plan(
            analysis,
            previous_plan=previous_plan,
            feedback=state.get("plans_feedback"),
        )
        return {
            "test_plan": plan.model_dump(),
            "audit_trail": ["test_plan_created"],
        }

    def approve_parallel_outputs(state: SdlcState) -> SdlcState:
        decision = cast(
            dict[str, Any],
            interrupt(
                {
                    "gate": "development_and_test_approval",
                    "artifacts": {
                        "development_plan": state["development_plan"],
                        "test_plan": state["test_plan"],
                    },
                    "allowed_decisions": ["approve", "reject"],
                }
            ),
        )
        result: SdlcState = {
            "human_decisions": {**state["human_decisions"], "plans": decision},
            "stage": (
                "ready_for_implementation" if _approved(decision) else "plans_revision_requested"
            ),
            "audit_trail": [f"parallel_plans_{decision.get('decision', 'invalid')}"],
        }
        if not _approved(decision):
            result["plans_feedback"] = str(decision.get("feedback", ""))
        return result

    def dispatch_parallel(_: SdlcState) -> SdlcState:
        return {"audit_trail": ["parallel_preparation_started"]}

    def send_parallel(state: SdlcState) -> list[Send]:
        return [
            Send("prepare_development_plan", state),
            Send("prepare_test_plan", state),
        ]

    def route_after_parallel_approval(
        state: SdlcState,
    ) -> list[Send] | Literal["__end__"]:
        if _approved(state["human_decisions"]["plans"]):
            return cast(Literal["__end__"], END)
        return send_parallel(state)

    builder = StateGraph(SdlcState)
    builder.add_node("draft_analysis", draft_analysis)
    builder.add_node("approve_analysis", approve_analysis)
    builder.add_node("prepare_development_plan", prepare_development_plan)
    builder.add_node("prepare_test_plan", prepare_test_plan)
    builder.add_node("approve_parallel_outputs", approve_parallel_outputs)
    builder.add_node("dispatch_parallel", cast(Any, dispatch_parallel))
    if entry_stage == "analysis":
        builder.add_edge(START, "draft_analysis")
    else:
        builder.add_edge(START, "dispatch_parallel")
        builder.add_conditional_edges("dispatch_parallel", send_parallel)
    builder.add_edge("draft_analysis", "approve_analysis")
    builder.add_conditional_edges(
        "approve_analysis",
        route_after_analysis,
    )
    builder.add_edge("prepare_development_plan", "approve_parallel_outputs")
    builder.add_edge("prepare_test_plan", "approve_parallel_outputs")
    builder.add_conditional_edges(
        "approve_parallel_outputs",
        route_after_parallel_approval,
    )
    return builder.compile(checkpointer=checkpointer)
