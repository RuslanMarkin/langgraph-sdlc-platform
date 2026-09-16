import pytest

from agent_platform import observability
from agent_platform.settings import Settings


class _FakeLangfuse:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def auth_check(self) -> bool:
        return True


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key="sk-lf-test",
        langfuse_base_url="https://cloud.langfuse.com",
    )


def test_callbacks_use_langfuse_base_url_and_verify_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[_FakeLangfuse] = []

    def build_client(**kwargs: object) -> _FakeLangfuse:
        client = _FakeLangfuse(**kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(observability, "Langfuse", build_client)
    monkeypatch.setattr(observability, "CallbackHandler", lambda: "callback")

    assert observability.langfuse_callbacks(_settings()) == ["callback"]
    assert created[0].kwargs["base_url"] == "https://cloud.langfuse.com"


def test_callbacks_stop_workflow_when_langfuse_rejects_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RejectedLangfuse(_FakeLangfuse):
        def auth_check(self) -> bool:
            return False

    monkeypatch.setattr(observability, "Langfuse", RejectedLangfuse)

    with pytest.raises(RuntimeError, match="Langfuse не авторизовал ключи"):
        observability.langfuse_callbacks(_settings())
