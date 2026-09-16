"""Environment-backed configuration. Secrets are never stored in source control."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for model and observability providers."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    model_provider: Literal["openai", "deepseek"] = "openai"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    deepseek_api_key: str | None = None
    deepseek_model: str = "deepseek-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    approval_channel: Literal["terminal", "github"] = "terminal"
    github_token: str | None = None
    github_repository: str = "RuslanMarkin/CRM_Almaz"
    github_approval_poll_seconds: int = 10
    sdlc_database_url: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def model_api_key(self) -> str | None:
        """Return the credential for the selected model provider."""
        if self.model_provider == "deepseek":
            return self.deepseek_api_key
        return self.openai_api_key

    @property
    def active_model(self) -> str:
        """Return the model name configured for the selected provider."""
        if self.model_provider == "deepseek":
            return self.deepseek_model
        return self.openai_model

    @property
    def model_base_url(self) -> str | None:
        """Use DeepSeek's OpenAI-compatible endpoint when selected."""
        if self.model_provider == "deepseek":
            return self.deepseek_base_url
        return None

    @property
    def github_approval_enabled(self) -> bool:
        """Return whether GitHub is selected and has the required credential."""
        return self.approval_channel == "github" and bool(self.github_token)


@lru_cache
def get_settings() -> Settings:
    return Settings()
