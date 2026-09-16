"""Versioned Langfuse chat prompts used by the SDLC agents."""

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langfuse import get_client, propagate_attributes

from agent_platform.settings import Settings


@dataclass(frozen=True)
class ManagedChatPrompt:
    """A compiled prompt together with the immutable Langfuse version that produced it."""

    name: str
    version: int
    messages: list[BaseMessage]
    client: Any


class LangfusePromptManager:
    """Fetch, compile and link approved prompt versions to Langfuse traces."""

    def __init__(self, settings: Settings) -> None:
        if not settings.langfuse_enabled:
            raise RuntimeError("Для управляемых подсказок задайте ключи Langfuse.")
        self.label = settings.langfuse_prompt_label
        self.cache_ttl_seconds = settings.langfuse_prompt_cache_ttl_seconds

    def compile_chat(self, name: str, **variables: str) -> ManagedChatPrompt:
        """Load one labelled chat prompt and substitute only runtime data."""
        prompt = get_client().get_prompt(
            name,
            label=self.label,
            type="chat",
            cache_ttl_seconds=self.cache_ttl_seconds,
        )
        compiled = prompt.compile(**variables)
        if not isinstance(compiled, list):
            raise RuntimeError(f"Prompt {name} должен быть chat-prompt в Langfuse.")
        return ManagedChatPrompt(
            name=str(prompt.name),
            version=int(prompt.version),
            messages=[self._to_message(item) for item in compiled],
            client=prompt,
        )

    @staticmethod
    def _to_message(item: object) -> BaseMessage:
        if not isinstance(item, Mapping):
            raise RuntimeError("Langfuse вернул некорректное сообщение prompt.")
        role = item.get("role")
        content = item.get("content")
        if not isinstance(content, str):
            raise RuntimeError("Сообщение prompt должно иметь строковое content.")
        if role == "system":
            return SystemMessage(content=content)
        if role == "user":
            return HumanMessage(content=content)
        raise RuntimeError(f"Неподдерживаемая роль {role!r} в SDLC prompt.")

    @staticmethod
    def trace_context(prompt: ManagedChatPrompt) -> AbstractContextManager[Any]:
        """Attach the exact Langfuse prompt version to nested LangChain generations."""
        return cast(AbstractContextManager[Any], propagate_attributes(prompt=prompt.client))
