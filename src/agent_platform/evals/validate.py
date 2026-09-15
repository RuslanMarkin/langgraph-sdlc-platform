"""CLI для проверки формата локального eval-dataset без сетевых запросов."""

import sys
from pathlib import Path

from agent_platform.evals.dataset import load_cases


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Использование: python -m agent_platform.evals.validate <путь-к-jsonl>")

    path = Path(sys.argv[1])
    cases = load_cases(path)
    print(f"Dataset валиден: {path} ({len(cases)} сценарий(ев))")


if __name__ == "__main__":
    main()
