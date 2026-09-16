import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from agent_platform import prompt_management
from agent_platform.prompt_management import LangfusePromptManager
from agent_platform.settings import Settings


class _FakePrompt:
    name = "sdlc/analyst-specification"
    version = 3

    def __init__(self) -> None:
        self.variables: dict[str, str] = {}

    def compile(self, **variables: str) -> list[dict[str, str]]:
        self.variables = variables
        return [
            {"role": "system", "content": "Роль: " + variables["role"]},
            {"role": "user", "content": "Задача: " + variables["request"]},
        ]


class _FakeClient:
    def __init__(self, prompt: _FakePrompt) -> None:
        self.prompt = prompt
        self.request: dict[str, object] = {}

    def get_prompt(self, name: str, **kwargs: object) -> _FakePrompt:
        self.request = {"name": name, **kwargs}
        return self.prompt


def test_managed_prompt_uses_production_label_and_compiles_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_prompt = _FakePrompt()
    fake_client = _FakeClient(fake_prompt)
    monkeypatch.setattr(prompt_management, "get_client", lambda: fake_client)
    manager = LangfusePromptManager(
        Settings(
            _env_file=None,
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
            langfuse_prompt_label="staging",
            langfuse_prompt_cache_ttl_seconds=15,
        )
    )

    compiled = manager.compile_chat("sdlc/analyst-specification", role="аналитик", request="CRM-1")

    assert fake_client.request == {
        "name": "sdlc/analyst-specification",
        "label": "staging",
        "type": "chat",
        "cache_ttl_seconds": 15,
    }
    assert compiled.name == "sdlc/analyst-specification"
    assert compiled.version == 3
    assert compiled.messages == [
        SystemMessage(content="Роль: аналитик"),
        HumanMessage(content="Задача: CRM-1"),
    ]


def test_managed_prompts_require_langfuse_keys() -> None:
    with pytest.raises(RuntimeError, match="задайте ключи Langfuse"):
        LangfusePromptManager(
            Settings(_env_file=None, langfuse_public_key=None, langfuse_secret_key=None)
        )
