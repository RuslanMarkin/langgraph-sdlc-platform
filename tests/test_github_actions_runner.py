from agent_platform.github_approval import is_recoverable_final_approval


def test_closed_final_approval_can_recover_the_post_approval_delivery() -> None:
    assert is_recoverable_final_approval(
        approval_issue={"state": "closed"},
        issue_gate="development_and_test_approval",
        decision={"decision": "approve"},
        pending_gate=None,
        workflow_stage="ready_for_implementation",
    )


def test_recovery_rejects_an_unrelated_or_incomplete_graph_state() -> None:
    assert not is_recoverable_final_approval(
        approval_issue={"state": "closed"},
        issue_gate="analyst_approval",
        decision={"decision": "approve"},
        pending_gate=None,
        workflow_stage="analysis_approved",
    )
