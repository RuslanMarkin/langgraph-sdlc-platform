"""GitHub Issues as a human approval interface for LangGraph interrupts."""

import json
import re
import time
from base64 import b64encode
from dataclasses import dataclass
from typing import Any, cast
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
THREAD_MARKER_PATTERN = re.compile(r"<!-- sdlc-thread:(?P<thread_id>[^\n]+) -->")
APPROVAL_MARKER_PATTERN = re.compile(r"<!-- sdlc-approval:[^:\n]+:(?P<gate>[^\s>]+) -->")


@dataclass(frozen=True)
class GitHubApprovalConfig:
    """Connection details for one repository-scoped approval channel."""

    token: str
    repository: str
    poll_seconds: int = 10


def is_trusted_author(payload: dict[str, Any]) -> bool:
    """Allow costly SDLC work only for repository participants."""
    return payload.get("author_association") in TRUSTED_ASSOCIATIONS


def parse_approval_comment(comment: dict[str, Any]) -> dict[str, Any] | None:
    """Translate a trusted GitHub comment into a LangGraph resume value."""
    if not is_trusted_author(comment):
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


def parse_thread_marker(issue_body: str) -> str | None:
    """Extract the LangGraph thread identifier stored in an approval Issue."""
    match = THREAD_MARKER_PATTERN.search(issue_body)
    return match.group("thread_id") if match else None


def parse_approval_gate_marker(issue_body: str) -> str | None:
    """Read the expected interrupt gate from an approval Issue."""
    match = APPROVAL_MARKER_PATTERN.search(issue_body)
    return match.group("gate") if match else None


def is_recoverable_final_approval(
    *,
    approval_issue: dict[str, Any],
    issue_gate: str | None,
    decision: dict[str, Any],
    pending_gate: str | None,
    workflow_stage: str | None,
) -> bool:
    """Allow retry only for a completed final approval after a delivery failure."""
    return (
        approval_issue.get("state") == "closed"
        and issue_gate == "development_and_test_approval"
        and decision.get("decision") == "approve"
        and pending_gate is None
        and workflow_stage == "ready_for_implementation"
    )


def feature_branch_name(feature_id: str, title: str) -> str:
    """Build a deterministic, repository-safe branch name from one approved feature."""
    normalized_id = re.sub(r"[^a-z0-9]+", "-", feature_id.lower()).strip("-")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"sdlc/{normalized_id or 'feature'}-{(slug or 'handoff')[:48]}"


def render_feature_handoff(
    *,
    feature_id: str,
    title: str,
    source_issue_url: str,
    analysis: dict[str, Any],
    development_plan: dict[str, Any],
    test_plan: dict[str, Any],
) -> str:
    """Create the only initial branch change: a reviewable handoff artifact."""
    sections = [
        ("Утверждённая аналитическая спецификация", analysis),
        ("Утверждённый план разработки", development_plan),
        ("Утверждённый QA-план", test_plan),
    ]
    rendered_sections = "\n\n".join(
        f"## {heading}\n\n```json\n{json.dumps(artifact, ensure_ascii=False, indent=2)}\n```"
        for heading, artifact in sections
    )
    return (
        f"# SDLC handoff: {feature_id}\n\n"
        f"**Бизнес-задача:** [{title}]({source_issue_url})\n\n"
        "Этот файл автоматически создан после human approval. На данном этапе "
        "ветка не содержит продуктовых изменений: реализация должна выполняться "
        "только в этом draft PR и проходить обычный GitHub review.\n\n"
        f"{rendered_sections}\n"
    )


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
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed GitHub API origin
                return cast(Any, json.loads(response.read().decode("utf-8")))
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")[-1_000:]
            raise RuntimeError(
                f"GitHub API {method} {path} вернул {error.code}: {details}"
            ) from error

    def create_gate_issue(
        self,
        *,
        feature_id: str,
        title: str,
        gate: str,
        artifact: dict[str, Any],
        thread_id: str | None = None,
    ) -> tuple[int, str]:
        """Publish the review artifact and return the new issue number and URL."""
        artifact_json = json.dumps(artifact, ensure_ascii=False, indent=2)
        marker = f"<!-- sdlc-approval:{feature_id}:{gate} -->"
        thread_marker = f"\n<!-- sdlc-thread:{thread_id} -->" if thread_id else ""
        body = (
            f"{marker}{thread_marker}\n\n"
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

    def get_issue(self, issue_number: int) -> dict[str, Any]:
        """Load one Issue so an event-driven runner can validate its marker."""
        issue = self._request("GET", f"/issues/{issue_number}")
        if not isinstance(issue, dict):
            raise RuntimeError("GitHub вернул некорректный ответ для Issue.")
        return cast(dict[str, Any], issue)

    def get_comment(self, comment_id: int) -> dict[str, Any]:
        """Load the exact comment delivered by the GitHub issue_comment event."""
        comment = self._request("GET", f"/issues/comments/{comment_id}")
        if not isinstance(comment, dict):
            raise RuntimeError("GitHub вернул некорректный ответ для комментария.")
        return cast(dict[str, Any], comment)

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
                self.complete_issue(issue_number, decision)
                return decision
            time.sleep(self.config.poll_seconds)

    def complete_issue(self, issue_number: int, decision: dict[str, Any]) -> None:
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

    def add_issue_comment(self, issue_number: int, body: str) -> None:
        """Publish implementation evidence in the timeline of a draft pull request."""
        self._request("POST", f"/issues/{issue_number}/comments", {"body": body})

    def create_draft_feature_pr(
        self,
        *,
        feature_id: str,
        title: str,
        base_branch: str,
        source_issue_url: str,
        analysis: dict[str, Any],
        development_plan: dict[str, Any],
        test_plan: dict[str, Any],
    ) -> tuple[str, int, str]:
        """Create one isolated handoff branch and a draft PR, idempotently."""
        branch = feature_branch_name(feature_id, title)
        self._ensure_branch(branch, base_branch)
        handoff_path = f"docs/sdlc/{feature_id}.md"
        self._ensure_handoff_document(
            branch=branch,
            path=handoff_path,
            content=render_feature_handoff(
                feature_id=feature_id,
                title=title,
                source_issue_url=source_issue_url,
                analysis=analysis,
                development_plan=development_plan,
                test_plan=test_plan,
            ),
        )
        existing = self._find_open_pr(branch)
        if existing:
            return branch, int(existing["number"]), str(existing["html_url"])
        pull_request = self._request(
            "POST",
            "/pulls",
            {
                "title": f"[SDLC] {feature_id}: {title}",
                "head": branch,
                "base": base_branch,
                "draft": True,
                "body": (
                    "## Автоматически созданный handoff\n\n"
                    f"Исходная бизнес-задача: {source_issue_url}\n\n"
                    f"Первый коммит содержит [{handoff_path}]({handoff_path}) с утверждёнными "
                    "артефактами. Следующий ограниченный этап может добавить реализацию строго "
                    "в разрешённые файлы этой ветки. Агент не может выполнить merge.\n\n"
                    "После изменений обязательны CI и human review."
                ),
            },
        )
        return branch, int(pull_request["number"]), str(pull_request["html_url"])

    def _ensure_branch(self, branch: str, base_branch: str) -> None:
        branch_ref = f"/git/ref/heads/{quote(branch, safe='/')}"
        try:
            self._request("GET", branch_ref)
            return
        except HTTPError as error:
            if error.code != 404:
                raise
        base_ref = self._request("GET", f"/git/ref/heads/{quote(base_branch, safe='/')}")
        self._request(
            "POST",
            "/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": str(base_ref["object"]["sha"])},
        )

    def _ensure_handoff_document(self, *, branch: str, path: str, content: str) -> None:
        encoded_branch = quote(branch, safe="")
        try:
            self._request("GET", f"/contents/{path}?ref={encoded_branch}")
            return
        except HTTPError as error:
            if error.code != 404:
                raise
        self._request(
            "PUT",
            f"/contents/{path}",
            {
                "message": "Добавить утверждённый SDLC handoff",
                "content": b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": branch,
            },
        )

    def _find_open_pr(self, branch: str) -> dict[str, Any] | None:
        owner, _ = self.config.repository.split("/", maxsplit=1)
        pulls = self._request(
            "GET", f"/pulls?state=open&head={quote(f'{owner}:{branch}', safe='')}"
        )
        if not isinstance(pulls, list):
            raise RuntimeError("GitHub вернул некорректный список pull request.")
        return cast(dict[str, Any], pulls[0]) if pulls else None
