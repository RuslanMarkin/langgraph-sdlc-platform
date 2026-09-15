"""Явный запуск локального dataset как Langfuse Experiment."""

from collections.abc import Callable
from typing import Any

from langfuse import Langfuse, get_client
from langfuse.experiment import ExperimentItem

from agent_platform.evals.dataset import EvaluationCase
from agent_platform.evals.graders import exact_match
from agent_platform.settings import Settings

EvaluationTask = Callable[[Any], Any]


def run_local_experiment(
    *,
    settings: Settings,
    name: str,
    cases: list[EvaluationCase],
    task: EvaluationTask,
    description: str,
    metadata: dict[str, str] | None = None,
) -> Any:
    """Запустить task на локальном dataset и отправить оценки в Langfuse."""
    if not settings.langfuse_enabled:
        raise RuntimeError("Для запуска эксперимента задайте ключи Langfuse в .env")

    Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    client = get_client()

    def experiment_task(*, item: ExperimentItem, **_: dict[str, Any]) -> Any:
        if not isinstance(item, dict):
            raise TypeError("Локальный запуск evals ожидает локальный dataset")
        return task(item["input"])

    result = client.run_experiment(
        name=name,
        description=description,
        data=[case.to_langfuse_item() for case in cases],
        task=experiment_task,
        evaluators=[exact_match],
        metadata=metadata or {},
    )
    client.flush()
    return result
