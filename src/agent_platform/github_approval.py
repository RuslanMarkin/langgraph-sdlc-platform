"""GitHub Issues as a human approval interface for LangGraph interrupts."""

import json
import time
from dataclasses import dataclass
from typing import Any, cast
from urllib.request import Request, urlopen

TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


@dataclass(frozen=True)
class GitHubApprovalConfig:
    """Connection details for one repository-scoped approval channel."""

    token: str
    repository: str
    poll_seconds: int = 10


def parse_approval_comment(comment: dict[str, Any]) -> dict[str, Any] | None:
    """Translate a trusted GitHub comment into a LangGraph resume value."""
    if comment.get("author_association") not in TRUSTED_ASSOCIATIONS:
        return None
    body = str(comment.get("body", "")).strip()
    user = comment.get("user")
    if not isinstance(user, dict) or not user.get("login"):
        return None

    decision: str
    feedback = ""
    if body == "/approve":
        decision = "approve"
    elif body.startswith("/reject "):
        decision = "reject"
        feedback = body.removeprefix("/reject ").strip()
        if not feedback:
            return None
    else:
        return None

    return {
        "decision": decision,
        "reviewer": str(user["login"]),
        "feedback": feedback,
        "source": "github",
        "source_url": str(comment.get("html_url", "")),
        "submitted_at": str(comment.get("created_at", "")),
    }


class GitHubApprovalGateway:
    """Create approval issues and wait for a trusted slash command."""

    def __init__(self, config: GitHubApprovalConfig) -> None:
        if "/" not in config.repository:
            raise ValueError("GITHUB_REPOSITORY должен иметь формат owner/repository.")
        self.config = config
        self.api_root = f"https://api.github.com/repos/{config.repository}"

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.api_root}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.config.token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed GitHub API origin
            return cast(Any, json.loads(response.read().decode("utf-8")))

    def create_gate_issue(
        self,
        *,
        feature_id: str,
        title: str,
        gate: str,
        artifact: dict[str, Any],
    ) -> tuple[int, str]:
        """Publish the review artifact and return the new issue number and URL."""
        artifact_json = json.dumps(artifact, ensure_ascii=False, indent=2)
        marker = f"<!-- sdlc-approval:{feature_id}:{gate} -->"
        body = (
            f"{marker}\n\n"
            f"Автоматический human gate **{gate}** для `{feature_id}`.\n\n"
            "<details><summary>Артефакт для проверки</summary>\n\n"
            f"```json\n{artifact_json}\n```\n\n</details>\n\n"
            "Оставьте отдельный комментарий:\n\n"
            "- `/approve` — утвердить;\n"
            "- `/reject причина` — вернуть агенту на доработку.\n\n"
            "Решения принимаются только от владельца или участника репозитория."
        )
        if len(body) > 60_000:
            raise ValueError(
                "Артефакт слишком велик для GitHub Issue (лимит пилота: 60 000 знаков)."
            )
        issue = self._request(
            "POST",
            "/issues",
            {"title": f"[Согласование] {feature_id}: {title} — {gate}", "body": body},
        )
        return int(issue["number"]), str(issue["html_url"])

    def wait_for_decision(self, issue_number: int) -> dict[str, Any]:
        """Poll issue comments until a trusted reviewer submits a valid command."""
        last_comment_id = 0
        while True:
            comments = self._request(
                "GET", f"/issues/{issue_number}/comments?per_page=100&sort=created&direction=asc"
            )
            for comment in comments:
                comment_id = int(comment.get("id", 0))
                if comment_id <= last_comment_id:
                    continue
                last_comment_id = comment_id
                decision = parse_approval_comment(comment)
                if decision is None:
                    continue
                self._complete_issue(issue_number, decision)
                return decision
            time.sleep(self.config.poll_seconds)

    def _complete_issue(self, issue_number: int, decision: dict[str, Any]) -> None:
        decision_label = "утверждено" if decision["decision"] == "approve" else "отклонено"
        reviewer = decision["reviewer"]
        source_url = decision["source_url"]
        self._request(
            "POST",
            f"/issues/{issue_number}/comments",
            {
                "body": (
                    f"Решение **{decision_label}** принято от @{reviewer}.\n\n"
                    f"[Комментарий с решением]({source_url}) передан в LangGraph."
                )
            },
        )
        self._request("PATCH", f"/issues/{issue_number}", {"state": "closed"})
