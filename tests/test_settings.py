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
