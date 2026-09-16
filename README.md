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
| `MODEL_PROVIDER` | `openai` или `deepseek` | нет для smoke-check |
| `OPENAI_API_KEY` | Ключ OpenAI | только при `MODEL_PROVIDER=openai` |
| `OPENAI_MODEL` | Модель по умолчанию | нет |
| `DEEPSEEK_API_KEY` | Ключ DeepSeek | только при `MODEL_PROVIDER=deepseek` |
| `DEEPSEEK_MODEL` | Модель DeepSeek, по умолчанию `deepseek-flash` | нет |
| `DEEPSEEK_BASE_URL` | OpenAI-совместимый endpoint DeepSeek | нет |
| `LANGFUSE_PUBLIC_KEY` | Публичный ключ проекта Langfuse | да для телеметрии |
| `LANGFUSE_SECRET_KEY` | Секретный ключ проекта Langfuse | да для телеметрии |
| `LANGFUSE_HOST` | Региональный endpoint Langfuse | нет |

Никогда не коммитьте `.env` или ключи в GitHub. Для CI-сценариев добавляйте секреты через **Settings → Secrets and variables → Actions**.

## Следующий шаг

После готовности инфраструктуры определите первый прикладной workflow. Для него зафиксируем входной контракт, ожидаемый результат, набор тестовых примеров и критерии оценки в Langfuse, затем реализуем граф отдельной feature-веткой.

## Human-gated SDLC workflow

`agent_platform.sdlc_workflow` — первый прикладной graph. Он работает так:

1. Агент-аналитик читает только явно разрешённые файлы проекта и создаёт
   структурированный черновик спецификации.
2. Graph останавливается на `analyst_approval`; аналитик явно выбирает
   `approve` или `reject`. При `reject` замечания и предыдущий черновик
   возвращаются агенту-аналитику, после чего человек получает новую версию.
3. Только после `approve` параллельно запускаются агент планирования разработки
   и независимый QA-агент, создающий план автоматических и staging-проверок из
   той же спецификации.
4. Человек утверждает или отклоняет оба пакета. При `reject` его замечания и
   предыдущие версии одновременно возвращаются Developer- и QA-агентам, после
   чего graph снова останавливается на проверке обновлённых пакетов. До
   `approve` состояние `ready_for_implementation` недостижимо.

Для локального демо используется `InMemorySaver`. Перед подключением к реальной
GitHub-автоматизации его нужно заменить на постоянный checkpointer PostgreSQL:
это сохраняет ожидание решения человека при перезапуске процесса. Реальные
LLM-агенты активируются только при локально заданном ключе выбранного провайдера:
`OPENAI_API_KEY` или `DEEPSEEK_API_KEY`. Без него в CI работают
детерминированные тестовые двойники.

Запуск пилота с реальными агентами выполняется только вручную и не меняет
репозиторий. Сначала создайте вне Git файл `request.json`:

```json
{
  "feature_id": "CP-STATUS-002",
  "title": "Пример новой функции",
  "description": "Кратко опишите бизнес-потребность."
}
```

Затем явно перечислите файлы, которые аналитик может прочитать:

```bash
docker compose run --rm app python -m agent_platform.run_sdlc_pilot \
  --request /work/input/request.json \
  --project-root /work/crm-almaz \
  --evidence drizzle/schema.ts \
  --evidence server/routers.ts \
  --evidence client/src/pages/Counterparties.tsx
```

Команда покажет каждый artifact и запросит JSON-решение человека. Например,
`{"decision":"approve","reviewer":"Иван Петров"}`. При отклонении graph
запускает повторную подготовку соответствующего артефакта и снова ждёт человека.

Перед запуском создайте локальную, некоммитируемую папку `sdlc-input/` и
положите в неё `request.json`. CRM подключается в контейнер только для чтения
как `/work/crm-almaz`; агент не может записывать в него из этого workflow.

### Подтверждения через GitHub

При `APPROVAL_CHANNEL=github` каждый LangGraph interrupt создаёт Issue в
`GITHUB_REPOSITORY` с полным артефактом. Владелец или участник репозитория
оставляет комментарий `/approve` либо `/reject причина`. Команда сохраняется
в состоянии с GitHub-логином, ссылкой и временем, Issue закрывается, а graph
продолжает выполнение.

Если аналитика уже была утверждена, повторную параллельную подготовку планов
можно начать без нового вызова аналитика:

```bash
docker compose run --rm app python -m agent_platform.run_sdlc_pilot \
  --request /work/input/request.json \
  --project-root /work/crm-almaz \
  --approved-analysis /work/input/approved-analysis.json \
  --plans-feedback-file /work/input/plans-feedback.txt \
  --plans-feedback-reviewer RuslanMarkin \
  --plans-feedback-source-url https://github.com/owner/repository/issues/1#issuecomment-1
```

Для локального пилота добавьте в `.env` fine-grained token с доступом только к
целевому репозиторию и правом **Issues: Read and write**:

```text
APPROVAL_CHANNEL=github
GITHUB_TOKEN=github_pat_...
GITHUB_REPOSITORY=RuslanMarkin/CRM_Almaz
```

Локальный процесс должен оставаться запущенным, пока ожидается решение. Для
облачного многопользовательского режима следующим шагом потребуется постоянный
LangGraph checkpointer вместо `InMemorySaver`.
