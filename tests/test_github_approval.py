import pytest

from agent_platform.github_approval import (
    GitHubApprovalConfig,
    GitHubApprovalGateway,
    is_trusted_author,
    parse_approval_comment,
    parse_approval_gate_marker,
    parse_thread_marker,
)


def github_comment(body: str, association: str = "OWNER") -> dict[str, object]:
    return {
        "body": body,
        "author_association": association,
        "user": {"login": "RuslanMarkin"},
        "html_url": "https://github.com/example/repo/issues/1#issuecomment-1",
        "created_at": "2026-09-16T10:00:00Z",
    }


def test_owner_can_approve() -> None:
    decision = parse_approval_comment(github_comment("/approve"))

    assert decision == {
        "decision": "approve",
        "reviewer": "RuslanMarkin",
        "feedback": "",
        "source": "github",
        "source_url": "https://github.com/example/repo/issues/1#issuecomment-1",
        "submitted_at": "2026-09-16T10:00:00Z",
    }


def test_rejection_requires_feedback() -> None:
    assert parse_approval_comment(github_comment("/reject")) is None

    decision = parse_approval_comment(github_comment("/reject Исправить команды проверки"))
    assert decision is not None
    assert decision["decision"] == "reject"
    assert decision["feedback"] == "Исправить команды проверки"


def test_untrusted_public_comment_is_ignored() -> None:
    assert parse_approval_comment(github_comment("/approve", association="NONE")) is None
    assert not is_trusted_author(github_comment("текст", association="NONE"))


def test_repository_participant_can_start_sdlc() -> None:
    assert is_trusted_author(github_comment("текст", association="COLLABORATOR"))


def test_thread_marker_is_read_from_approval_issue_body() -> None:
    body = (
        "<!-- sdlc-approval:CRM-42:analyst_approval -->\n<!-- sdlc-thread:github:CRM:issue:42 -->"
    )

    assert parse_thread_marker(body) == "github:CRM:issue:42"
    assert parse_thread_marker("обычный Issue") is None
    assert parse_approval_gate_marker(body) == "analyst_approval"
    assert parse_approval_gate_marker("обычный Issue") is None


def test_gateway_reads_comment_from_repository_wide_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = GitHubApprovalGateway(
        GitHubApprovalConfig(token="test-token", repository="owner/repo")
    )
    calls: list[tuple[str, str, object]] = []

    def request(method: str, path: str, payload: object = None) -> dict[str, object]:
        calls.append((method, path, payload))
        return github_comment("/approve")

    monkeypatch.setattr(gateway, "_request", request)

    assert gateway.get_comment(123) == github_comment("/approve")
    assert calls == [("GET", "/issues/comments/123", None)]
