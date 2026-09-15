# LangGraph SDLC Platform

Стартовая инфраструктура для разработки AI-функций по управляемому SDLC-процессу.

## Состав

- **LangChain** — адаптеры моделей, промпты и инструменты.
- **LangGraph** — версионируемые графы workflow, состояния и human-in-the-loop.
- **Langfuse Cloud** — трассировки, метрики стоимости, промпты, датасеты и оценки.
- **Docker** — одинаковая среда разработки и CI.
- **GitHub Actions** — проверки форматирования, типов и тестов на каждый pull request.

Продуктовая логика намеренно не задана: первый graph — это только smoke-check окружения. Новая функциональность добавляется отдельной веткой и заменяет его либо расширяет.

## Evals

В проекте есть готовая структура для воспроизводимых оценок: versioned JSONL
datasets, deterministic graders и adapter к Langfuse Experiments. Подробный
контракт и порядок работы — в [evals/README.md](evals/README.md).

## Быстрый старт

### 1. Создайте проект в Langfuse Cloud

1. Зарегистрируйтесь на [Langfuse Cloud](https://cloud.langfuse.com) и создайте проект.
2. В настройках проекта создайте API keys.
3. Скопируйте шаблон окружения: `cp .env.example .env`.
4. Заполните `LANGFUSE_PUBLIC_KEY` и `LANGFUSE_SECRET_KEY`.

Для европейского региона оставьте `LANGFUSE_HOST=https://cloud.langfuse.com`; для US-региона замените адрес на `https://us.cloud.langfuse.com`.

### 2. Установите Docker Desktop

На macOS: `brew install --cask docker`, затем откройте Docker Desktop и дождитесь статуса *Engine running*.

### 3. Проверьте проект

```bash
docker compose build
docker compose run --rm app pytest
docker compose run --rm app python -m agent_platform.healthcheck
```

Последняя команда создаст одну тестовую трассировку в Langfuse, если ключи заполнены. Без ключей workflow остаётся работоспособным, а отправка телеметрии отключается.

### 4. Проследить передачу прикладной задачи

После слияния разработки запускайте graph handoff для конкретной фичи. Он
передаёт только ссылки на версионируемые GitHub-артефакты и результаты gate-проверок,
поэтому любой узел trace можно сопоставить с исходным кодом и PR.

```bash
docker compose run --rm app python -m agent_platform.trace_counterparty_status
```

Команда демонстрирует передачу `CP-STATUS-001` из разработки в QA и создаёт
trace в Langfuse с именем `CP-STATUS-001: передача разработки в QA`. Новые
фичи получают свой входной state и отдельный `thread_id`; ключи Langfuse при
этом остаются только в локальном `.env`.

## Работа с ветками

`main` — только проверенный код. Для каждой функции создавайте ветку от `main`:

```bash
git switch main
git pull --ff-only
git switch -c feature/<краткое-название>
```

Открывайте pull request в `main`; CI должен завершиться успешно до merge. Рекомендуем включить в настройках GitHub репозитория branch protection для `main`: требовать pull request и успешный статус `CI / test`.

## Переменные окружения

| Переменная | Назначение | Обязательна |
| --- | --- | --- |
| `OPENAI_API_KEY` | Ключ провайдера модели для будущих графов | нет для smoke-check |
| `OPENAI_MODEL` | Модель по умолчанию | нет |
| `LANGFUSE_PUBLIC_KEY` | Публичный ключ проекта Langfuse | да для телеметрии |
| `LANGFUSE_SECRET_KEY` | Секретный ключ проекта Langfuse | да для телеметрии |
| `LANGFUSE_HOST` | Региональный endpoint Langfuse | нет |

Никогда не коммитьте `.env` или ключи в GitHub. Для CI-сценариев добавляйте секреты через **Settings → Secrets and variables → Actions**.

## Следующий шаг

После готовности инфраструктуры определите первый прикладной workflow. Для него зафиксируем входной контракт, ожидаемый результат, набор тестовых примеров и критерии оценки в Langfuse, затем реализуем граф отдельной feature-веткой.
