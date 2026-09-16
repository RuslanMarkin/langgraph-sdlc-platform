"""LangChain agents and safe repository-reading tools for SDLC workflows."""

from pathlib import Path
from typing import Any, Protocol, cast

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, SecretStr, field_validator

from agent_platform.observability import langfuse_callbacks
from agent_platform.prompt_management import LangfusePromptManager
from agent_platform.settings import Settings


class BusinessRequest(BaseModel):
    """A business request supplied to the analyst agent."""

    feature_id: str
    title: str
    description: str


class AnalysisDraft(BaseModel):
    """Structured result that must be approved by a human analyst."""

    summary: str
    scope: list[str] = Field(min_length=1)
    non_goals: list[str] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    affected_files: list[str] = Field(min_length=1)
    risks_and_questions: list[str]


class DevelopmentPlan(BaseModel):
    """A developer agent's plan; it is not permission to write code yet."""

    implementation_steps: list[str] = Field(min_length=1)
    files_to_change: list[str] = Field(min_length=1)
    migration_plan: str
    verification_commands: list[str] = Field(min_length=1)


class TestPlanDraft(BaseModel):
    """Tests derived independently from the approved analysis specification."""

    automated_tests: list[str] = Field(min_length=1)
    manual_staging_checks: list[str] = Field(min_length=1)
    regression_risks: list[str]


class ImplementationPatch(BaseModel):
    """A constrained code change emitted by the implementation agent."""

    summary: str = Field(min_length=1)
    unified_diff: str = Field(min_length=1)

    @field_validator("unified_diff")
    @classmethod
    def require_unified_diff_header(cls, value: str) -> str:
        """Reject prose and blank JSON values before a patch reaches Git."""
        normalized = value.strip()
        if not normalized.startswith("diff --git a/"):
            raise ValueError("unified_diff должен начинаться с заголовка diff --git a/.")
        return normalized


class AnalystAgent(Protocol):
    def draft(
        self,
        request: BusinessRequest,
        repository_evidence: str,
        *,
        previous_draft: AnalysisDraft | None = None,
        feedback: str | None = None,
    ) -> AnalysisDraft:
        """Produce an analysis draft from the request and read-only evidence."""


class DeveloperPlannerAgent(Protocol):
    def plan(
        self,
        analysis: AnalysisDraft,
        *,
        previous_plan: DevelopmentPlan | None = None,
        feedback: str | None = None,
    ) -> DevelopmentPlan:
        """Prepare a code plan from an approved specification."""


class TestDesignerAgent(Protocol):
    def plan(
        self,
        analysis: AnalysisDraft,
        *,
        previous_plan: TestPlanDraft | None = None,
        feedback: str | None = None,
    ) -> TestPlanDraft:
        """Prepare test design from an approved specification."""


def _build_chat_model(settings: Settings) -> ChatOpenAI:
    """Create an OpenAI-compatible client for the selected provider."""
    if not settings.model_api_key:
        key_name = "DEEPSEEK_API_KEY" if settings.model_provider == "deepseek" else "OPENAI_API_KEY"
        raise RuntimeError(f"Для запуска LLM-агентов задайте {key_name} в локальном .env.")

    arguments: dict[str, Any] = {
        "model": settings.active_model,
        "api_key": SecretStr(settings.model_api_key),
        "temperature": 0,
    }
    if settings.model_base_url:
        arguments["base_url"] = settings.model_base_url
    return ChatOpenAI(**arguments)


def _json_instruction(schema: type[BaseModel]) -> str:
    """Give JSON mode an explicit schema for provider-independent parsing."""
    return (
        "Верни только корректный JSON без Markdown, строго по этой JSON Schema:\n"
        f"{schema.model_json_schema()}"
    )


def _read_repository_evidence(project_root: str, paths: list[str]) -> str:
    """Read explicitly allowlisted files without letting a request escape the repository."""
    root = Path(project_root).resolve()
    snippets: list[str] = []
    for relative_path in paths:
        candidate = (root / relative_path).resolve()
        if root not in candidate.parents or not candidate.is_file():
            snippets.append(f"--- {relative_path} ---\n[Файл недоступен]")
            continue
        content = candidate.read_text(encoding="utf-8", errors="replace")
        snippets.append(f"--- {relative_path} ---\n{content[:8_000]}")
    return "\n\n".join(snippets)


@tool
def read_repository_evidence(project_root: str, paths: list[str]) -> str:
    """Read selected text files below one repository root for analysis only."""
    return _read_repository_evidence(project_root, paths)


class LangChainAnalystAgent:
    """LLM-backed analyst with a read-only repository evidence tool."""

    def __init__(self, settings: Settings) -> None:
        self.model = _build_chat_model(settings).with_structured_output(
            AnalysisDraft, method="json_mode"
        )
        self.prompts = LangfusePromptManager(settings)

    def draft(
        self,
        request: BusinessRequest,
        repository_evidence: str,
        *,
        previous_draft: AnalysisDraft | None = None,
        feedback: str | None = None,
    ) -> AnalysisDraft:
        revision_context = ""
        if previous_draft and feedback:
            revision_context = (
                "\n\nПредыдущий черновик:\n"
                f"{previous_draft.model_dump_json(indent=2)}\n\n"
                f"Замечания человека, обязательные для новой версии:\n{feedback}"
            )
        prompt = self.prompts.compile_chat(
            "sdlc/analyst-specification",
            output_schema=_json_instruction(AnalysisDraft),
            feature_id=request.feature_id,
            title=request.title,
            description=request.description,
            repository_evidence=repository_evidence,
            revision_context=revision_context,
        )
        with self.prompts.trace_context(prompt):
            response = self.model.invoke(prompt.messages)
        return cast(AnalysisDraft, response)


class LangChainDeveloperPlannerAgent:
    """LLM-backed planner that cannot write to a repository."""

    def __init__(self, settings: Settings) -> None:
        self.model = _build_chat_model(settings).with_structured_output(
            DevelopmentPlan, method="json_mode"
        )
        self.prompts = LangfusePromptManager(settings)

    def plan(
        self,
        analysis: AnalysisDraft,
        *,
        previous_plan: DevelopmentPlan | None = None,
        feedback: str | None = None,
    ) -> DevelopmentPlan:
        revision_parts: list[str] = []
        if previous_plan:
            revision_parts.append(
                f"Предыдущий план реализации:\n{previous_plan.model_dump_json(indent=2)}"
            )
        if feedback:
            revision_parts.append(f"Замечания человека, обязательные для новой версии:\n{feedback}")
        revision_context = "\n\n" + "\n\n".join(revision_parts) if revision_parts else ""
        prompt = self.prompts.compile_chat(
            "sdlc/development-plan",
            output_schema=_json_instruction(DevelopmentPlan),
            analysis_json=analysis.model_dump_json(indent=2),
            revision_context=revision_context,
        )
        with self.prompts.trace_context(prompt):
            response = self.model.invoke(prompt.messages)
        return cast(DevelopmentPlan, response)


class LangChainTestDesignerAgent:
    """LLM-backed test designer running independently of the developer planner."""

    def __init__(self, settings: Settings) -> None:
        self.model = _build_chat_model(settings).with_structured_output(
            TestPlanDraft, method="json_mode"
        )
        self.prompts = LangfusePromptManager(settings)

    def plan(
        self,
        analysis: AnalysisDraft,
        *,
        previous_plan: TestPlanDraft | None = None,
        feedback: str | None = None,
    ) -> TestPlanDraft:
        revision_parts: list[str] = []
        if previous_plan:
            revision_parts.append(
                f"Предыдущий тест-план:\n{previous_plan.model_dump_json(indent=2)}"
            )
        if feedback:
            revision_parts.append(f"Замечания человека, обязательные для новой версии:\n{feedback}")
        revision_context = "\n\n" + "\n\n".join(revision_parts) if revision_parts else ""
        prompt = self.prompts.compile_chat(
            "sdlc/qa-test-plan",
            output_schema=_json_instruction(TestPlanDraft),
            analysis_json=analysis.model_dump_json(indent=2),
            revision_context=revision_context,
        )
        with self.prompts.trace_context(prompt):
            response = self.model.invoke(prompt.messages)
        return cast(TestPlanDraft, response)


class LangChainImplementationAgent:
    """LLM-backed patch author that cannot execute commands or write files itself."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = _build_chat_model(settings).with_structured_output(
            ImplementationPatch, method="json_mode", include_raw=True
        )
        self.prompts = LangfusePromptManager(settings)

    def _invoke_patch(self, messages: list[BaseMessage]) -> tuple[ImplementationPatch | None, str]:
        """Read a parsed patch without treating a malformed model reply as executable output."""
        response = cast(
            dict[str, Any],
            self.model.invoke(
                messages,
                config=cast(Any, {"callbacks": langfuse_callbacks(self.settings)}),
            ),
        )
        patch = response.get("parsed")
        if isinstance(patch, ImplementationPatch):
            return patch, ""
        return None, str(response.get("parsing_error") or "модель не вернула валидный JSON-diff")

    def implement(
        self,
        *,
        analysis: AnalysisDraft,
        development_plan: DevelopmentPlan,
        test_plan: TestPlanDraft,
        project_root: str,
        evidence_paths: list[str],
        previous_patch: ImplementationPatch | None = None,
        validation_error: str | None = None,
    ) -> tuple[ImplementationPatch, list[str]]:
        """Generate one diff restricted to files approved in both plan and allowlist."""
        allowed_paths = sorted(set(development_plan.files_to_change) & set(evidence_paths))
        if not allowed_paths:
            raise RuntimeError(
                "План разработки не содержит файлов из разрешённого набора свидетельств."
            )
        prompt = self.prompts.compile_chat(
            "sdlc/implementation-patch",
            output_schema=_json_instruction(ImplementationPatch),
            allowed_paths=", ".join(allowed_paths),
            analysis_json=analysis.model_dump_json(indent=2),
            development_plan_json=development_plan.model_dump_json(indent=2),
            test_plan_json=test_plan.model_dump_json(indent=2),
            repository_evidence=_read_repository_evidence(project_root, allowed_paths),
        )
        repair_context: list[BaseMessage] = []
        if previous_patch and validation_error:
            repair_context.append(
                HumanMessage(
                    content=(
                        "Предыдущий unified diff не прошёл проверку Git. Сгенерируй полную "
                        "замену diff, а не объяснение. Ошибка Git:\n"
                        f"{validation_error}\n\nПредыдущий diff:\n{previous_patch.unified_diff}"
                    ),
                )
            )
        with self.prompts.trace_context(prompt):
            messages = [*prompt.messages, *repair_context]
            patch, error = self._invoke_patch(messages)
            if patch is None:
                patch, retry_error = self._invoke_patch(
                    [
                        *messages,
                        HumanMessage(
                            content=(
                                "Предыдущий ответ некорректен. Верни непустой unified diff: поле "
                                "unified_diff обязано начинаться с 'diff --git a/'. Не объясняй "
                                "причину и не возвращай пустую строку."
                            ),
                        ),
                    ]
                )
                if patch is None:
                    raise RuntimeError(
                        "Агент реализации дважды вернул некорректный diff: "
                        f"первая ошибка: {error}; повтор: {retry_error}"
                    )
        return patch, allowed_paths


def build_implementation_agent(settings: Settings) -> LangChainImplementationAgent:
    """Create the constrained code-authoring role for an approved feature branch."""
    return LangChainImplementationAgent(settings)


def build_production_agents(
    settings: Settings,
) -> tuple[AnalystAgent, DeveloperPlannerAgent, TestDesignerAgent]:
    """Create the three distinct LLM roles for a production-like pilot."""
    return (
        LangChainAnalystAgent(settings),
        LangChainDeveloperPlannerAgent(settings),
        LangChainTestDesignerAgent(settings),
    )
