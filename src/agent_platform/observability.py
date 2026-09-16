"""Optional Langfuse integration shared by all graphs."""

from collections.abc import Sequence
from typing import Any

from langfuse import Langfuse, get_client
from langfuse.langchain import CallbackHandler

from agent_platform.settings import Settings


def langfuse_callbacks(settings: Settings) -> Sequence[Any]:
    """Return callbacks only when the Langfuse project is reachable and authorized."""
    if not settings.langfuse_enabled:
        return []

    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
    )
    if not client.auth_check():
        raise RuntimeError(
            "Langfuse не авторизовал ключи. Проверьте LANGFUSE_PUBLIC_KEY, "
            "LANGFUSE_SECRET_KEY и LANGFUSE_BASE_URL."
        )
    return [CallbackHandler()]


def flush_langfuse(settings: Settings) -> None:
    """Deliver queued telemetry before a short-lived command exits."""
    if settings.langfuse_enabled:
        get_client().flush()
