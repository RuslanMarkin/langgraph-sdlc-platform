# Evals

Здесь живут проверяемые сценарии качества для будущих AI-функций. Структура
готова заранее, чтобы новая функция сразу появлялась вместе с тестовыми
примерами и измеримым критерием готовности.

## Состав

- `datasets/` — локальные, версионируемые JSONL-наборы. Один объект в строке —
  один сценарий.
- `src/agent_platform/evals/` — загрузка сценариев, deterministic graders и
  запуск экспериментов в Langfuse.
- `tests/` — проверка схемы наборов и graders без вызова модели и Langfuse.

## Контракт сценария

```json
{
  "id": "уникальный-id",
  "input": {"произвольный": "JSON-вход функции"},
  "expected_output": {"ожидаемый": "JSON-результат"},
  "metadata": {
    "category": "happy_path | edge_case | safety | regression",
    "risk": "low | medium | high"
  }
}
```

Не добавляйте в dataset персональные данные, API-ключи или содержимое реальных
документов без обезличивания.

## Как добавлять evals для новой функции

1. Создайте `evals/datasets/<название-функции>.jsonl`.
2. Добавьте как минимум happy path, edge case и один сценарий с высоким риском.
3. Определите deterministic grader. Если качество нельзя проверить строго,
   добавьте LLM-as-a-Judge отдельным следующим шагом.
4. Зафиксируйте минимальный проходной балл в pull request.
5. Прогоните локальную валидацию:

   ```bash
   docker compose run --rm app python -m agent_platform.evals.validate \
     evals/datasets/<название-функции>.jsonl
   ```

## Эксперименты в Langfuse

`runner.py` оборачивает локальный dataset в Langfuse Experiment. Каждый запуск
создаёт трассировки и оценки в Langfuse, поэтому он запускается явно, а не на
каждый CI-прогон. После появления первой прикладной функции добавим её adapter
и отдельную команду запуска эксперимента.

Локальные JSONL-файлы остаются источником версий в Git. Позже набор можно
загрузить в Langfuse Datasets для совместной разметки и сравнения версий.

### Проверка заземления аналитика

`datasets/analyst-evidence-grounding.jsonl` проверяет, что аналитик отличает
подтверждённое требование от отсутствующего или обрезанного свидетельства
кода. Для каждого сценария в output требуется:

- `evidence_assessment`: `confirmed`, `not_found` или `insufficient`;
- `evidence_references`: конкретные файлы, элементы или строки кода;
- риск в `risks_and_questions`, если цель не найдена или контекста недостаточно.

Запуск реального эксперимента с текущими production prompt и моделью:

```bash
docker compose run --rm app python -m agent_platform.evals.analyst_grounding \
  --dataset evals/datasets/analyst-evidence-grounding.jsonl \
  --name sdlc-analyst-evidence-grounding
```

Эксперимент создаёт по trace на каждый кейс и score
`analyst_evidence_grounding`. Этот deterministic grader проверяет контракт
заземления, но не заменяет human review содержания спецификации.
