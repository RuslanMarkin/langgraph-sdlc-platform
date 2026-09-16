"""LangChain agents and safe repository-reading tools for SDLC workflows."""

from pathlib import Path
from typing import Any, Protocol, cast

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, SecretStr

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


def build_production_agents(
    settings: Settings,
) -> tuple[AnalystAgent, DeveloperPlannerAgent, TestDesignerAgent]:
    """Create the three distinct LLM roles for a production-like pilot."""
    return (
        LangChainAnalystAgent(settings),
        LangChainDeveloperPlannerAgent(settings),
        LangChainTestDesignerAgent(settings),
    )
