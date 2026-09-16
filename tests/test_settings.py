import pytest

from agent_platform.settings import Settings


def test_langfuse_requires_both_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    assert not Settings(_env_file=None).langfuse_enabled
    assert not Settings(_env_file=None, langfuse_public_key="pk-lf-test").langfuse_enabled
    assert Settings(
        _env_file=None,
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key="sk-lf-test",
    ).langfuse_enabled


def test_deepseek_provider_selects_its_key_model_and_endpoint() -> None:
    settings = Settings(
        _env_file=None,
        model_provider="deepseek",
        deepseek_api_key="test-key",
        deepseek_model="deepseek-flash",
    )

    assert settings.model_api_key == "test-key"
    assert settings.active_model == "deepseek-flash"
    assert settings.model_base_url == "https://api.deepseek.com"


def test_openai_remains_the_default_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    settings = Settings(_env_file=None, openai_api_key="test-key")

    assert settings.model_provider == "openai"
    assert settings.model_api_key == "test-key"
    assert settings.active_model == "gpt-4.1-mini"
    assert settings.model_base_url is None
