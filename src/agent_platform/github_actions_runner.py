"""Short-lived, event-driven LangGraph runner for GitHub Actions."""

import argparse
import json
from typing import Any, cast

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

from agent_platform.github_approval import (
    GitHubApprovalConfig,
    GitHubApprovalGateway,
    is_recoverable_final_approval,
    is_trusted_author,
    parse_approval_comment,
    parse_approval_gate_marker,
    parse_thread_marker,
)
from agent_platform.implementation import FeatureBranchWorkspace
from agent_platform.observability import flush_langfuse, langfuse_callbacks
from agent_platform.sdlc_agents import (
    AnalysisDraft,
    DevelopmentPlan,
    TestPlanDraft,
    build_implementation_agent,
    build_production_agents,
)
from agent_platform.sdlc_workflow import build_sdlc_workflow
from agent_platform.settings import Settings, get_settings


def parse_args() -> argparse.Namespace:
    """Parse one GitHub event represented by workflow inputs."""
    parser = argparse.ArgumentParser(description="Event-driven SDLC runner for GitHub Actions")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project-root", required=True)
    common.add_argument("--evidence", action="append", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", parents=[common])
    start.add_argument("--issue-number", type=int, required=True)
    resume = subparsers.add_parser("resume", parents=[common])
    resume.add_argument("--approval-issue-number", type=int, required=True)
    resume.add_argument("--comment-id", type=int, required=True)
    return parser.parse_args()


def _require_database_url(settings: Settings) -> str:
    if not settings.sdlc_database_url:
        raise RuntimeError("Для GitHub Actions задайте Secret SDLC_DATABASE_URL.")
    return settings.sdlc_database_url


def _build_gateway(settings: Settings) -> GitHubApprovalGateway:
    if not settings.github_token:
        raise RuntimeError("GitHub Actions должен передать GITHUB_TOKEN.")
    return GitHubApprovalGateway(
        GitHubApprovalConfig(token=settings.github_token, repository=settings.github_repository)
    )


def _config(thread_id: str, settings: Settings) -> dict[str, Any]:
    return {
        "callbacks": langfuse_callbacks(settings),
        "configurable": {"thread_id": thread_id},
        "run_name": f"{thread_id}: GitHub SDLC runner",
        "tags": ["sdlc", "github-actions", "human-gated"],
    }


def _publish_interrupt(
    *,
    result: dict[str, Any],
    gateway: GitHubApprovalGateway,
    feature_id: str,
    title: str,
    thread_id: str,
) -> bool:
    """Publish one new approval Issue without changing the interrupted checkpoint."""
    if "__interrupt__" not in result:
        print(json.dumps({"status": "completed", "thread_id": thread_id}))
        return False
    artifact = cast(dict[str, Any], result["__interrupt__"][0].value)
    gate = str(artifact["gate"])
    issue_number, issue_url = gateway.create_gate_issue(
        feature_id=feature_id,
        title=title,
        gate=gate,
        artifact=artifact,
        thread_id=thread_id,
    )
    print(
        json.dumps({"status": "awaiting_approval", "issue_url": issue_url, "thread_id": thread_id})
    )
    return True


def _pending_gate(snapshot: Any) -> str | None:
    """Return the sole human gate currently suspended in a LangGraph checkpoint."""
    for task in snapshot.tasks:
        for pending_interrupt in task.interrupts:
            value = pending_interrupt.value
            if isinstance(value, dict) and isinstance(value.get("gate"), str):
                return cast(str, value["gate"])
    return None


def _finish_implementation(
    *,
    args: argparse.Namespace,
    settings: Settings,
    gateway: GitHubApprovalGateway,
    thread_id: str,
    completed_state: dict[str, Any],
) -> None:
    """Create or reuse the feature PR, then safely implement the approved plan."""
    request = cast(dict[str, Any], completed_state["request"])
    source_issue_number = thread_id.rsplit(":", maxsplit=1)[-1]
    source_issue_url = f"https://github.com/{settings.github_repository}/issues/{source_issue_number}"
    branch, pull_number, pull_url = gateway.create_draft_feature_pr(
        feature_id=str(request["feature_id"]),
        title=str(request["title"]),
        base_branch=settings.sdlc_base_branch,
        source_issue_url=source_issue_url,
        analysis=cast(dict[str, Any], completed_state["analysis_draft"]),
        development_plan=cast(dict[str, Any], completed_state["development_plan"]),
        test_plan=cast(dict[str, Any], completed_state["test_plan"]),
    )
    analysis = AnalysisDraft.model_validate(completed_state["analysis_draft"])
    development_plan = DevelopmentPlan.model_validate(completed_state["development_plan"])
    test_plan = TestPlanDraft.model_validate(completed_state["test_plan"])
    workspace = FeatureBranchWorkspace(args.project_root)
    workspace.checkout(branch)
    patch, allowed_paths = build_implementation_agent(settings).implement(
        analysis=analysis,
        development_plan=development_plan,
        test_plan=test_plan,
        project_root=args.project_root,
        evidence_paths=args.evidence,
    )
    verification = workspace.verify_commit_and_push(
        paths=workspace.apply_patch(patch, allowed_paths),
        feature_id=str(request["feature_id"]),
    )
    gateway.add_issue_comment(
        pull_number,
        (
            "## Реализация агентом завершена\n\n"
            f"{patch.summary}\n\n"
            f"Проверка: `{verification}`.\n\n"
            "PR остаётся draft. Перед переводом в review и merge требуется "
            "проверить изменения человеком."
        ),
    )
    print(
        json.dumps(
            {
                "status": "draft_pr_created",
                "branch": branch,
                "pull_number": pull_number,
                "pull_url": pull_url,
                "verification": verification,
                "thread_id": thread_id,
            }
        )
    )


def run_start(args: argparse.Namespace, settings: Settings) -> None:
    """Start an SDLC thread once from a labelled business Issue."""
    gateway = _build_gateway(settings)
    business_issue = gateway.get_issue(args.issue_number)
    if not is_trusted_author(business_issue):
        raise RuntimeError("Бизнес-Issue может запустить SDLC только от участника репозитория.")
    thread_id = f"github:{settings.github_repository}:issue:{args.issue_number}"
    config = _config(thread_id, settings)
    with PostgresSaver.from_conn_string(_require_database_url(settings)) as checkpointer:
        checkpointer.setup()
        analyst, developer, test_designer = build_production_agents(settings)
        graph = build_sdlc_workflow(analyst, developer, test_designer, checkpointer=checkpointer)
        if graph.get_state(config).values:
            print(json.dumps({"status": "already_started", "thread_id": thread_id}))
            return
        result = graph.invoke(
            {
                "request": {
                    "feature_id": f"CRM-{args.issue_number}",
                    "title": str(business_issue["title"]),
                    "description": str(business_issue.get("body") or ""),
                },
                "project_root": args.project_root,
                "evidence_paths": args.evidence,
                "stage": "new",
                "audit_trail": ["github_business_issue_received"],
                "human_decisions": {},
            },
            config=config,
        )
        _publish_interrupt(
            result=cast(dict[str, Any], result),
            gateway=gateway,
            feature_id=f"CRM-{args.issue_number}",
            title=str(business_issue["title"]),
            thread_id=thread_id,
        )


def run_resume(args: argparse.Namespace, settings: Settings) -> None:
    """Resume a persisted graph from one trusted GitHub approval comment."""
    gateway = _build_gateway(settings)
    approval_issue = gateway.get_issue(args.approval_issue_number)
    thread_id = parse_thread_marker(str(approval_issue.get("body") or ""))
    if not thread_id:
        raise RuntimeError("Issue не содержит маркер LangGraph thread_id.")
    issue_gate = parse_approval_gate_marker(str(approval_issue.get("body") or ""))
    comment = gateway.get_comment(args.comment_id)
    decision = parse_approval_comment(comment)
    if decision is None:
        print(json.dumps({"status": "ignored_comment", "thread_id": thread_id}))
        return
    config = _config(thread_id, settings)
    with PostgresSaver.from_conn_string(_require_database_url(settings)) as checkpointer:
        checkpointer.setup()
        analyst, developer, test_designer = build_production_agents(settings)
        graph = build_sdlc_workflow(analyst, developer, test_designer, checkpointer=checkpointer)
        snapshot = graph.get_state(config)
        if is_recoverable_final_approval(
            approval_issue=approval_issue,
            issue_gate=issue_gate,
            decision=decision,
            pending_gate=_pending_gate(snapshot),
            workflow_stage=snapshot.values.get("stage"),
        ):
            _finish_implementation(
                args=args,
                settings=settings,
                gateway=gateway,
                thread_id=thread_id,
                completed_state=cast(dict[str, Any], snapshot.values),
            )
            return
        if approval_issue.get("state") != "open" or issue_gate != _pending_gate(snapshot):
            print(json.dumps({"status": "stale_comment", "thread_id": thread_id}))
            return
        result = graph.invoke(Command(resume=decision), config=config)
        gateway.complete_issue(args.approval_issue_number, decision)
        request = cast(dict[str, Any], graph.get_state(config).values["request"])
        interrupted = _publish_interrupt(
            result=cast(dict[str, Any], result),
            gateway=gateway,
            feature_id=str(request["feature_id"]),
            title=str(request["title"]),
            thread_id=thread_id,
        )
        if interrupted:
            return
        _finish_implementation(
            args=args,
            settings=settings,
            gateway=gateway,
            thread_id=thread_id,
            completed_state=cast(dict[str, Any], graph.get_state(config).values),
        )


def main() -> None:
    """Run exactly one start or resume event, then exit for GitHub Actions."""
    args = parse_args()
    settings = get_settings()
    try:
        if args.command == "start":
            run_start(args, settings)
        else:
            run_resume(args, settings)
    finally:
        flush_langfuse(settings)


if __name__ == "__main__":
    main()
