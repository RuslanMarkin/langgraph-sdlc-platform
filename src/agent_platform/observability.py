"""Optional Langfuse integration shared by all graphs."""

from collections.abc import Sequence
from typing import Any

from langfuse import Langfuse, get_client
from langfuse.langchain import CallbackHandler

from agent_platform.settings import Settings


def langfuse_callbacks(settings: Settings) -> Sequence[Any]:
    """Return callbacks only when the project has valid Langfuse credentials."""
    if not settings.langfuse_enabled:
        return []

    Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    return [CallbackHandler()]


def flush_langfuse(settings: Settings) -> None:
    """Deliver queued telemetry before a short-lived command exits."""
    if settings.langfuse_enabled:
        get_client().flush()
