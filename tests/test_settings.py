from agent_platform.settings import Settings


def test_langfuse_requires_both_keys() -> None:
    assert not Settings().langfuse_enabled
    assert not Settings(langfuse_public_key="pk-lf-test").langfuse_enabled
    assert Settings(
        langfuse_public_key="pk-lf-test", langfuse_secret_key="sk-lf-test"
    ).langfuse_enabled
