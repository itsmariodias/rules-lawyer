from __future__ import annotations

import pytest

from rules_lawyer.config import ChatSettings, EmbeddingSettings
from rules_lawyer.providers import PROVIDERS, Provider

NO_KEYS = {"google_api_key": None, "openai_api_key": None,
           "anthropic_api_key": None}


def chat(provider: Provider, **overrides) -> ChatSettings:
    """Chat settings for ``provider`` with no keys, whatever ``.env`` says."""
    values = NO_KEYS | {"provider": provider, "model": "test-model",
                        "temperature": 0.2, "max_tokens": None,
                        "openai_base_url": None}
    return ChatSettings(**(values | overrides))


class TestProviders:
    def test_given_every_provider_name_when_looked_up_then_each_has_its_class(self):
        # Given the values CHAT_PROVIDER and EMBED_PROVIDER accept
        # When each is looked up
        # Then every one has a provider that names itself
        assert set(PROVIDERS) == set(Provider)
        assert all(provider.name is name for name, provider in PROVIDERS.items())

    def test_given_each_provider_when_its_key_variable_is_read_then_it_names_its_field(
            self):
        # Given each provider
        # When its key variable is read
        variables = {name: provider.key_variable
                     for name, provider in PROVIDERS.items()}

        # Then each names its own, and Ollama, running locally, none
        assert variables == {Provider.GOOGLE: "GOOGLE_API_KEY",
                             Provider.OPENAI: "OPENAI_API_KEY",
                             Provider.ANTHROPIC: "ANTHROPIC_API_KEY",
                             Provider.OLLAMA: None}


class TestApiKey:
    def test_given_several_keys_when_read_then_only_the_providers_own_is_returned(
            self):
        # Given settings holding every provider's key
        settings = chat(Provider.OPENAI, google_api_key="g", openai_api_key="o",
                        anthropic_api_key="a")

        # When each provider reads its key
        keys = {name: provider.api_key(settings)
                for name, provider in PROVIDERS.items()}

        # Then each gets its own, and Ollama none
        assert keys[Provider.GOOGLE].get_secret_value() == "g"
        assert keys[Provider.OPENAI].get_secret_value() == "o"
        assert keys[Provider.ANTHROPIC].get_secret_value() == "a"
        assert keys[Provider.OLLAMA] is None


class TestChatOptions:
    def test_given_a_key_and_a_cap_when_built_then_both_are_passed(self):
        # Given Anthropic with a key and a reply cap
        settings = chat(Provider.ANTHROPIC, anthropic_api_key="a", max_tokens=512)

        # When its options are read
        options = PROVIDERS[Provider.ANTHROPIC].chat_options(settings)

        # Then the key is passed explicitly, beside the temperature and cap
        assert options == {"api_key": "a", "temperature": 0.2, "max_tokens": 512}

    def test_given_no_temperature_when_built_then_each_provider_sends_its_own(self):
        # Given no temperature set, for each provider
        # When each one's options are read
        sent = {name: provider.chat_options(chat(name, temperature=None))
                .get("temperature", "none")
                for name, provider in PROVIDERS.items()}

        # Then the hosted models, which deprecate it, get none; Ollama gets 0.2
        assert sent == {Provider.GOOGLE: "none", Provider.OPENAI: "none",
                        Provider.ANTHROPIC: "none", Provider.OLLAMA: 0.2}

    def test_given_a_temperature_when_built_then_it_is_sent_whatever_the_provider(
            self):
        # Given a temperature set for a provider whose default sends none
        settings = chat(Provider.GOOGLE, temperature=0.5)

        # When its options are read
        # Then the setting wins over the provider's default
        assert PROVIDERS[Provider.GOOGLE].chat_options(settings)["temperature"] == 0.5

    def test_given_gemini_when_built_then_only_the_pinned_model_thinks_low(self):
        # Given the pinned Gemini model, and another Gemini model
        pinned = chat(Provider.GOOGLE, model=PROVIDERS[Provider.GOOGLE].chat_model)
        other = chat(Provider.GOOGLE, model="gemini-2.5-flash")

        # When their options are read
        # Then the pinned model thinks at "low", and the other at its own default
        assert PROVIDERS[Provider.GOOGLE].chat_options(pinned)["thinking_level"] == "low"
        assert "thinking_level" not in PROVIDERS[Provider.GOOGLE].chat_options(other)

    def test_given_openai_when_built_then_usage_is_streamed_from_the_given_server(
            self):
        # Given OpenAI pointed at a compatible server
        settings = chat(Provider.OPENAI, openai_api_key="o",
                        openai_base_url="http://localhost:1234/v1")

        # When its options are read
        options = PROVIDERS[Provider.OPENAI].chat_options(settings)

        # Then usage arrives on streamed calls, from that server
        assert options["stream_usage"] is True
        assert options["base_url"] == "http://localhost:1234/v1"

    def test_given_ollama_when_built_then_the_server_and_its_cap_name_are_used(
            self):
        # Given Ollama with a reply cap
        settings = chat(Provider.OLLAMA, max_tokens=512,
                        ollama_base_url="http://ollama.test:11434")

        # When its options are read
        options = PROVIDERS[Provider.OLLAMA].chat_options(settings)

        # Then there is no key, and the cap goes under Ollama's own name
        assert options == {"temperature": 0.2, "num_predict": 512,
                           "base_url": "http://ollama.test:11434"}


class TestEmbedder:
    def test_given_anthropic_when_asked_to_embed_then_it_is_refused(self):
        # Given a provider with no embeddings API, past the settings check
        settings = EmbeddingSettings(provider="google", google_api_key=None)

        # When it is asked for an embedder
        # Then it refuses by name
        with pytest.raises(ValueError, match="Anthropic has no embeddings API"):
            PROVIDERS[Provider.ANTHROPIC].embedder(settings)


class TestEmbeddingsName:
    def test_given_google_when_named_then_it_is_the_shared_file(self):
        # Given the distributed name
        # When Google names its file
        # Then it is that file, which holds Gemini's vectors
        assert PROVIDERS[Provider.GOOGLE].embeddings_name(
            "srd_embeddings.idx") == "srd_embeddings.idx"

    def test_given_another_provider_when_named_then_its_name_is_before_the_suffix(
            self):
        # Given the distributed name
        # When OpenAI names its file
        # Then it is a sibling, never the shared file
        assert PROVIDERS[Provider.OPENAI].embeddings_name(
            "srd_embeddings.idx") == "srd_embeddings.openai.idx"


class TestExplain:
    def test_given_a_provider_without_its_own_failures_when_asked_then_it_defers(
            self):
        # Given Google and a connection refused
        # When it is asked to explain
        # Then it leaves the error to the generic handling
        assert PROVIDERS[Provider.GOOGLE].explain(
            "ConnectError: Connection refused", chat(Provider.GOOGLE)) is None

    def test_given_ollama_not_running_when_explained_then_it_says_how_to_start_it(
            self):
        # Given Ollama configured but not listening
        settings = chat(Provider.OLLAMA, ollama_base_url="http://localhost:11434")

        # When the refusal is explained
        explained = PROVIDERS[Provider.OLLAMA].explain(
            "ConnectError: [Errno 61] Connection refused", settings)

        # Then it names the address and the setting to change
        assert "not reachable at http://localhost:11434" in explained
        assert "OLLAMA_BASE_URL" in explained

    def test_given_an_ollama_model_not_pulled_when_explained_then_it_says_to_pull_it(
            self):
        # Given Ollama without the configured model
        settings = chat(Provider.OLLAMA, model="qwen3")

        # When its refusal is explained
        explained = PROVIDERS[Provider.OLLAMA].explain(
            "ResponseError: model 'qwen3' not found", settings)

        # Then it gives the command that fixes it
        assert "ollama pull qwen3" in explained
