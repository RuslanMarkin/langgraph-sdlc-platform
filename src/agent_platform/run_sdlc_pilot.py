"""Run the human-gated SDLC pilot locally with real LangChain agents."""

import argparse
import json
from pathlib import Path
from typing import Any, cast

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent_platform.github_approval import GitHubApprovalConfig, GitHubApprovalGateway
from agent_platform.observability import flush_langfuse, langfuse_callbacks
from agent_platform.sdlc_agents import build_production_agents
from agent_platform.sdlc_workflow import build_sdlc_workflow
from agent_platform.settings import Settings, get_settings


def parse_args() -> argparse.Namespace:
    """Parse paths deliberately supplied by the human running the pilot."""
    parser = argparse.ArgumentParser(description="Запуск human-gated SDLC-пилота")
    parser.add_argument("--request", required=True, help="Путь к JSON бизнес-задаче")
    parser.add_argument(
        "--project-root", required=True, help="Корень репозитория для read-only анализа"
    )
    parser.add_argument(
        "--evidence",
        action="append",
        required=True,
        help="Относительный путь к файлу, который агенту разрешено прочитать; можно повторять",
    )
    return parser.parse_args()


def read_terminal_decision(gate: str) -> dict[str, Any]:
    """Require an explicit structured human decision before graph resumption."""
    while True:
        raw = input(f"Решение для {gate} (JSON, например {{\"decision\": \"approve\"}}): ")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            print("Нужен корректный JSON.")
            continue
        if not isinstance(parsed, dict):
            print("Решение должно быть JSON-объектом.")
            continue
        decision = cast(dict[str, Any], parsed)
        if decision.get("decision") not in {"approve", "reject"}:
            print('Допустимы только решения "approve" или "reject".')
            continue
        return decision


def build_github_gateway(settings: Settings) -> GitHubApprovalGateway | None:
    """Build the selected external approval channel, if configured."""
    if settings.approval_channel != "github":
        return None
    if not settings.github_token:
        raise RuntimeError(
            "Для APPROVAL_CHANNEL=github задайте GITHUB_TOKEN в локальном .env."
        )
    return GitHubApprovalGateway(
        GitHubApprovalConfig(
            token=settings.github_token,
            repository=settings.github_repository,
            poll_seconds=settings.github_approval_poll_seconds,
        )
    )


def main() -> None:
    """Start and resume one in-memory pilot session until it reaches a final state."""
    args = parse_args()
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    settings = get_settings()
    github_gateway = build_github_gateway(settings)
    analyst, developer, test_designer = build_production_agents(settings)
    graph = build_sdlc_workflow(
        analyst,
        developer,
        test_designer,
        checkpointer=InMemorySaver(),
    )
    config = {
        "callbacks": langfuse_callbacks(settings),
        "configurable": {"thread_id": request["feature_id"]},
        "run_name": f"{request['feature_id']}: human-gated SDLC pilot",
        "tags": ["sdlc", "human-gated", "pilot"],
    }
    result = graph.invoke(
        {
            "request": request,
            "project_root": args.project_root,
            "evidence_paths": args.evidence,
            "stage": "new",
            "audit_trail": [],
        },
        config=config,
    )
    while "__interrupt__" in result:
        artifact = cast(dict[str, Any], result["__interrupt__"][0].value)
        gate = str(artifact["gate"])
        print("\nАртефакт для проверки:\n")
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
        if github_gateway:
            issue_number, issue_url = github_gateway.create_gate_issue(
                feature_id=str(request["feature_id"]),
                title=str(request["title"]),
                gate=gate,
                artifact=artifact,
            )
            print(f"\nОжидается решение в GitHub: {issue_url}")
            decision = github_gateway.wait_for_decision(issue_number)
        else:
            decision = read_terminal_decision(gate)
        result = graph.invoke(Command(resume=decision), config=config)

    flush_langfuse(settings)
    print("\nФинальное состояние:\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
