from __future__ import annotations

import pytest

from rules_lawyer import providers
from rules_lawyer.chat.agent import model


class TestModel:
    def test_given_no_api_key_when_built_then_it_is_reported_not_raised_at_import(
            self, settings_env, monkeypatch):
        # Given settings with the key removed (``.env`` may supply one, so
        # unsetting the environment variable is not enough)
        settings = settings_env(CHAT_PROVIDER="google")
        monkeypatch.setattr(settings.chat, "google_api_key", None)

        # When the model is built
        # Then the failure names the setting and what to do about it
        with pytest.raises(model.ModelUnavailable, match="GOOGLE_API_KEY"):
            model.model()

    def test_given_a_key_when_built_then_the_pinned_model_is_used(
            self, settings_env, monkeypatch):
        # Given a key in the environment
        monkeypatch.setenv("GOOGLE_API_KEY", "not-a-real-key")
        settings = settings_env(CHAT_PROVIDER="google")

        # When the model is built
        built = model.model()

        # Then it is the configured model, at the configured temperature
        assert built.model.endswith(settings.chat.model)
        assert built.temperature == settings.chat.temperature

    def test_given_no_temperature_when_gemini_is_built_then_none_is_sent(
            self, settings_env, monkeypatch):
        # Given Gemini, which deprecates temperature, with none set
        monkeypatch.setenv("GOOGLE_API_KEY", "not-a-real-key")
        settings_env(CHAT_PROVIDER="google", CHAT_TEMPERATURE="")

        # When the model is built
        built = model.model()

        # Then none is sent, rather than LangChain's own default
        assert built.temperature is None

    def test_given_a_blank_key_when_built_then_it_counts_as_no_key_at_all(
            self, settings_env, monkeypatch):
        # Given a key blanked out rather than removed
        monkeypatch.setenv("GOOGLE_API_KEY", "   ")
        settings_env(CHAT_PROVIDER="google")

        # When the model is built
        # Then it fails the way a missing key does
        with pytest.raises(model.ModelUnavailable, match="GOOGLE_API_KEY"):
            model.model()

    def test_given_anthropic_when_built_then_its_key_and_model_are_used(
            self, settings_env):
        # Given Anthropic configured with a key from the settings
        pytest.importorskip("langchain_anthropic")
        settings_env(CHAT_PROVIDER="anthropic", CHAT_MODEL="claude-test",
                     ANTHROPIC_API_KEY="not-a-real-key")

        # When the model is built
        built = model.model()

        # Then it is Anthropic's, with the key passed rather than read from
        # an environment that ``.env`` never reaches
        assert type(built).__name__ == "ChatAnthropic"
        assert built.model == "claude-test"
        assert built.anthropic_api_key.get_secret_value() == "not-a-real-key"

    def test_given_openai_when_built_then_usage_is_streamed_and_the_url_kept(
            self, settings_env):
        # Given OpenAI pointed at a compatible server
        pytest.importorskip("langchain_openai")
        settings_env(CHAT_PROVIDER="openai", CHAT_MODEL="gpt-test",
                     OPENAI_API_KEY="not-a-real-key",
                     OPENAI_BASE_URL="http://localhost:1234/v1")

        # When the model is built
        built = model.model()

        # Then usage arrives on streamed calls, at the given server
        assert type(built).__name__ == "ChatOpenAI"
        assert built.model_name == "gpt-test"
        assert built.stream_usage is True
        assert built.openai_api_base == "http://localhost:1234/v1"

    def test_given_ollama_when_built_then_no_key_is_needed(self, settings_env):
        # Given Ollama, which runs locally, and a token cap
        pytest.importorskip("langchain_ollama")
        settings_env(CHAT_PROVIDER="ollama", CHAT_MODEL="qwen3",
                     CHAT_MAX_TOKENS="512",
                     OLLAMA_BASE_URL="http://ollama.test:11434")

        # When the model is built
        built = model.model()

        # Then it is built without a key, the cap under Ollama's own name
        assert type(built).__name__ == "ChatOllama"
        assert built.base_url == "http://ollama.test:11434"
        assert built.num_predict == 512

    def test_given_a_blank_temperature_when_built_then_the_providers_own_is_kept(
            self, settings_env):
        # Given an OpenAI model, which may accept only its own temperature
        pytest.importorskip("langchain_openai")
        settings_env(CHAT_PROVIDER="openai", CHAT_MODEL="gpt-test",
                     OPENAI_API_KEY="not-a-real-key", CHAT_TEMPERATURE="")

        # When the model is built
        built = model.model()

        # Then no temperature was sent
        assert built.temperature is None

    def test_given_a_provider_without_a_model_when_built_then_it_names_the_setting(
            self, settings_env, monkeypatch):
        # Given Anthropic with a key but no model, which has no pinned default
        monkeypatch.delenv("CHAT_MODEL", raising=False)
        settings = settings_env(CHAT_PROVIDER="anthropic",
                                ANTHROPIC_API_KEY="not-a-real-key")
        monkeypatch.setattr(settings.chat, "model", None)

        # When the model is built
        # Then the failure says which setting is missing
        with pytest.raises(model.ModelUnavailable, match="CHAT_MODEL"):
            model.model()

    def test_given_an_uninstalled_package_when_built_then_the_extra_is_named(
            self, settings_env, monkeypatch):
        # Given a provider whose package is not installed
        settings_env(CHAT_PROVIDER="ollama", CHAT_MODEL="qwen3")

        def missing(*_, **__):
            raise ImportError("No module named 'langchain_ollama'")

        monkeypatch.setattr(providers.Ollama, "chat", missing)

        # When the model is built
        # Then the failure says how to install it
        with pytest.raises(model.ModelUnavailable,
                           match="uv sync --extra ollama"):
            model.model()
