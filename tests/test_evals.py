import json
from pathlib import Path

import pytest

from agent_platform.evals.analyst_grounding import analyst_evidence_grounding
from agent_platform.evals.dataset import EvaluationCase, load_cases
from agent_platform.evals.graders import exact_match


def test_smoke_dataset_is_valid() -> None:
    path = Path("evals/datasets/infrastructure-smoke.jsonl")
    cases = load_cases(path)

    assert len(cases) == 1
    assert cases[0].case_id == "infrastructure-healthcheck-001"


def test_analyst_grounding_dataset_is_valid() -> None:
    cases = load_cases(Path("evals/datasets/analyst-evidence-grounding.jsonl"))

    assert [case.case_id for case in cases] == [
        "column-confirmed",
        "column-not-found",
        "column-evidence-truncated",
    ]


def test_dataset_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    record = {
        "id": "duplicate",
        "input": "input",
        "expected_output": "output",
        "metadata": {},
    }
    dataset = tmp_path / "duplicate.jsonl"
    dataset.write_text("\n".join([json.dumps(record), json.dumps(record)]), encoding="utf-8")

    with pytest.raises(ValueError, match="повторяющийся"):
        load_cases(dataset)


def test_exact_match_is_order_independent_for_json_objects() -> None:
    score = exact_match(output={"a": 1, "b": 2}, expected_output={"b": 2, "a": 1})

    assert score.value == 1.0


def test_case_converts_to_langfuse_item() -> None:
    case = EvaluationCase(
        case_id="case-1",
        input={"query": "test"},
        expected_output="result",
        metadata={"risk": "low"},
    )

    assert case.to_langfuse_item()["metadata"]["case_id"] == "case-1"


def test_analyst_grounding_requires_a_matching_assessment_and_risk() -> None:
    score = analyst_evidence_grounding(
        output={
            "evidence_assessment": "not_found",
            "evidence_references": ["client/src/pages/Counterparties.tsx"],
            "risks_and_questions": ["Столбец не найден"],
        },
        expected_output={"evidence_assessment": "not_found", "requires_risk": True},
    )

    assert score.value == 1.0
