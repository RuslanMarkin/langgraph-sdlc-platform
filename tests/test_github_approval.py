from agent_platform.github_approval import parse_approval_comment, parse_thread_marker


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


def test_thread_marker_is_read_from_approval_issue_body() -> None:
    body = (
        "<!-- sdlc-approval:CRM-42:analyst_approval -->\n<!-- sdlc-thread:github:CRM:issue:42 -->"
    )

    assert parse_thread_marker(body) == "github:CRM:issue:42"
    assert parse_thread_marker("обычный Issue") is None
