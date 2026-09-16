"""Experiment and deterministic evaluator for evidence-grounded analyst specifications."""

import argparse
from pathlib import Path
from typing import Any

from langfuse import Evaluation

from agent_platform.evals.dataset import EvaluationCase, load_cases
from agent_platform.evals.runner import run_local_experiment
from agent_platform.sdlc_agents import BusinessRequest, LangChainAnalystAgent
from agent_platform.settings import Settings, get_settings


def analyst_evidence_grounding(
    *, output: Any, expected_output: Any, **_: Any
) -> Evaluation:
    """Score whether the analyst labels evidence availability and raises required risk."""
    if not isinstance(output, dict) or not isinstance(expected_output, dict):
        return Evaluation(
            name="analyst_evidence_grounding",
            value=0.0,
            comment="Grader получил некорректный формат результата или ожидания.",
        )

    expected_assessment = expected_output.get("evidence_assessment")
    assessment_matches = output.get("evidence_assessment") == expected_assessment
    references_present = bool(output.get("evidence_references"))
    risks = output.get("risks_and_questions")
    risk_present = isinstance(risks, list) and bool(risks)
    requires_risk = bool(expected_output.get("requires_risk"))
    risk_matches = risk_present if requires_risk else True
    checks = [assessment_matches, references_present, risk_matches]
    value = sum(checks) / len(checks)
    comment = (
        f"assessment={'ok' if assessment_matches else 'ошибка'}; "
        f"references={'ok' if references_present else 'нет'}; "
        f"risk={'ok' if risk_matches else 'нет'}"
    )
    return Evaluation(name="analyst_evidence_grounding", value=value, comment=comment)


def run_analyst_grounding_experiment(
    *, settings: Settings, cases: list[EvaluationCase], name: str
) -> Any:
    """Run the production analyst prompt against a versioned synthetic dataset."""
    analyst = LangChainAnalystAgent(settings)

    def task(case_input: Any) -> dict[str, Any]:
        if not isinstance(case_input, dict):
            raise TypeError("Вход analyst eval должен быть JSON-объектом.")
        request = BusinessRequest.model_validate(case_input["request"])
        evidence = str(case_input["repository_evidence"])
        return analyst.draft(request, evidence).model_dump()

    return run_local_experiment(
        settings=settings,
        name=name,
        cases=cases,
        task=task,
        description="Проверка, что аналитик не выдаёт предположения за свидетельства кода.",
        metadata={"agent": "analyst", "grader": "analyst_evidence_grounding"},
        evaluators=[analyst_evidence_grounding],
    )


def main() -> None:
    """Run the analyst evidence-grounding experiment explicitly from a developer machine."""
    parser = argparse.ArgumentParser(description="Запустить eval аналитика в Langfuse")
    parser.add_argument(
        "--dataset",
        default="evals/datasets/analyst-evidence-grounding.jsonl",
        type=Path,
    )
    parser.add_argument("--name", default="sdlc-analyst-evidence-grounding")
    args = parser.parse_args()
    run_analyst_grounding_experiment(
        settings=get_settings(), cases=load_cases(args.dataset), name=args.name
    )
    print(f"Langfuse Experiment запущен: {args.name}")


if __name__ == "__main__":
    main()
