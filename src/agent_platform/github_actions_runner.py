"""Short-lived, event-driven LangGraph runner for GitHub Actions."""

import argparse
import json
from typing import Any, cast

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

from agent_platform.github_approval import (
    GitHubApprovalConfig,
    GitHubApprovalGateway,
    is_trusted_author,
    parse_approval_comment,
    parse_thread_marker,
)
from agent_platform.observability import flush_langfuse, langfuse_callbacks
from agent_platform.sdlc_agents import build_production_agents
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
    graph: Any,
    config: dict[str, Any],
    result: dict[str, Any],
    gateway: GitHubApprovalGateway,
    feature_id: str,
    title: str,
    thread_id: str,
) -> None:
    """Publish one new approval Issue and persist its identity with the graph."""
    if "__interrupt__" not in result:
        graph.update_state(config, {"approval_gate": {"status": "completed"}})
        print(json.dumps({"status": "completed", "thread_id": thread_id}))
        return
    artifact = cast(dict[str, Any], result["__interrupt__"][0].value)
    gate = str(artifact["gate"])
    issue_number, issue_url = gateway.create_gate_issue(
        feature_id=feature_id,
        title=title,
        gate=gate,
        artifact=artifact,
        thread_id=thread_id,
    )
    graph.update_state(
        config,
        {
            "approval_gate": {
                "status": "awaiting",
                "issue_number": issue_number,
                "gate": gate,
                "issue_url": issue_url,
            }
        },
    )
    print(
        json.dumps({"status": "awaiting_approval", "issue_url": issue_url, "thread_id": thread_id})
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
            graph=graph,
            config=config,
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
        approval_gate = cast(dict[str, Any], snapshot.values.get("approval_gate") or {})
        if (
            approval_gate.get("status") != "awaiting"
            or approval_gate.get("issue_number") != args.approval_issue_number
        ):
            print(json.dumps({"status": "stale_comment", "thread_id": thread_id}))
            return
        graph.update_state(
            config,
            {
                "approval_gate": {
                    **approval_gate,
                    "status": "processing",
                    "comment_id": args.comment_id,
                }
            },
        )
        result = graph.invoke(Command(resume=decision), config=config)
        gateway.complete_issue(args.approval_issue_number, decision)
        request = cast(dict[str, Any], graph.get_state(config).values["request"])
        _publish_interrupt(
            graph=graph,
            config=config,
            result=cast(dict[str, Any], result),
            gateway=gateway,
            feature_id=str(request["feature_id"]),
            title=str(request["title"]),
            thread_id=thread_id,
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
