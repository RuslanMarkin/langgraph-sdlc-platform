"""Детерминированные graders без дополнительного вызова LLM."""

import json
from typing import Any

from langfuse import Evaluation


def exact_match(*, output: Any, expected_output: Any, **_: Any) -> Evaluation:
    """Оценить строгое совпадение JSON-совместимых результатов."""
    actual = json.dumps(output, ensure_ascii=False, sort_keys=True, default=str)
    expected = json.dumps(expected_output, ensure_ascii=False, sort_keys=True, default=str)
    passed = actual == expected
    if passed:
        comment = "Результат совпадает с ожидаемым."
    else:
        comment = "Результат отличается от ожидаемого."
    return Evaluation(
        name="exact_match",
        value=1.0 if passed else 0.0,
        comment=comment,
    )
