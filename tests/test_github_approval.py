import pytest

from agent_platform.github_approval import (
    GitHubApprovalConfig,
    GitHubApprovalGateway,
    feature_branch_name,
    is_trusted_author,
    parse_approval_comment,
    parse_approval_gate_marker,
    parse_thread_marker,
    render_feature_handoff,
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


def test_feature_branch_name_is_deterministic_and_safe() -> None:
    assert feature_branch_name("CRM-18", "Статусы контрагентов") == "sdlc/crm-18-handoff"
    assert feature_branch_name("CRM-18", "Add Counterparty Status") == (
        "sdlc/crm-18-add-counterparty-status"
    )


def test_feature_handoff_contains_only_review_artifacts() -> None:
    handoff = render_feature_handoff(
        feature_id="CRM-18",
        title="Статусы контрагентов",
        source_issue_url="https://github.com/owner/repo/issues/18",
        analysis={"summary": "Добавить статусы"},
        development_plan={"implementation_steps": ["Добавить поле"]},
        test_plan={"automated_tests": ["Проверить список"]},
    )

    assert "продуктовых изменений" in handoff
    assert "Добавить статусы" in handoff
    assert "Добавить поле" in handoff
    assert "Проверить список" in handoff


def test_feature_pr_is_reused_when_branch_already_has_an_open_pr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = GitHubApprovalGateway(
        GitHubApprovalConfig(token="test-token", repository="owner/repo")
    )
    monkeypatch.setattr(gateway, "_ensure_branch", lambda branch, base: None)
    monkeypatch.setattr(
        gateway,
        "_ensure_handoff_document",
        lambda *, branch, path, content: None,
    )
    monkeypatch.setattr(
        gateway,
        "_find_open_pr",
        lambda branch: {"number": 44, "html_url": "https://github.com/owner/repo/pull/44"},
    )

    branch, number, url = gateway.create_draft_feature_pr(
        feature_id="CRM-18",
        title="Статусы",
        base_branch="main",
        source_issue_url="https://github.com/owner/repo/issues/18",
        analysis={},
        development_plan={},
        test_plan={},
    )

    assert branch == "sdlc/crm-18-handoff"
    assert number == 44
    assert url == "https://github.com/owner/repo/pull/44"
