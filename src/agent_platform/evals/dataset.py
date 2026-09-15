"""Загрузка локальных версионируемых наборов eval-сценариев."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langfuse.experiment import LocalExperimentItem


@dataclass(frozen=True)
class EvaluationCase:
    """Один вход, ожидаемый результат и контекст оценки."""

    case_id: str
    input: Any
    expected_output: Any
    metadata: dict[str, Any]

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "EvaluationCase":
        required_fields = {"id", "input", "expected_output", "metadata"}
        missing_fields = required_fields.difference(record)
        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise ValueError(f"В сценарии отсутствуют обязательные поля: {missing}")

        if not isinstance(record["id"], str) or not record["id"]:
            raise ValueError("Поле id должно быть непустой строкой")
        if not isinstance(record["metadata"], dict):
            raise ValueError("Поле metadata должно быть JSON-объектом")

        return cls(
            case_id=record["id"],
            input=record["input"],
            expected_output=record["expected_output"],
            metadata=record["metadata"],
        )

    def to_langfuse_item(self) -> LocalExperimentItem:
        """Преобразовать локальный сценарий в формат Langfuse Experiment."""
        return {
            "input": self.input,
            "expected_output": self.expected_output,
            "metadata": {"case_id": self.case_id, **self.metadata},
        }


def load_cases(path: Path) -> list[EvaluationCase]:
    """Прочитать JSONL dataset и проверить уникальность идентификаторов."""
    cases: list[EvaluationCase] = []
    case_ids: set[str] = set()

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Строка {line_number}: некорректный JSON") from error
        if not isinstance(record, dict):
            raise ValueError(f"Строка {line_number}: сценарий должен быть JSON-объектом")

        case = EvaluationCase.from_record(record)
        if case.case_id in case_ids:
            raise ValueError(f"Строка {line_number}: повторяющийся id {case.case_id!r}")
        case_ids.add(case.case_id)
        cases.append(case)

    if not cases:
        raise ValueError("Dataset не содержит сценариев")
    return cases
