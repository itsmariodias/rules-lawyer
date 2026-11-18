"""The model providers: what each needs, and how its models are built.

Everything that differs between Google, OpenAI, Anthropic and Ollama is
here, so the settings, the chat and the embeddings ask the configured
provider rather than branching on its name.  Provider packages are imported
only when a model is built: they are optional extras, and ``parse`` needs
none of them.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from pydantic import SecretStr

    from rules_lawyer.config import ChatSettings, Credentials, EmbeddingSettings

# Embeds one batch of texts, one vector per text.
Embedder = Callable[[list[str]], list[list[float]]]


class Provider(StrEnum):
    """The values of ``CHAT_PROVIDER`` and ``EMBED_PROVIDER``."""

    GOOGLE = "google"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


class ModelProvider:
    """One provider.  Subclasses set what differs from these defaults.

    Attributes:
        name: Its ``Provider`` value, which is also the extra installing its
            package (``uv sync --extra ollama``).
        title: Its name as the reader knows it.
        langchain_name: ``init_chat_model``'s name for it.
        key_field: The ``Credentials`` field holding its key; None if it
            takes none.
        key_variable: That field's environment variable.
        chat_model: Its pinned chat model; None means ``CHAT_MODEL`` must
            name one.
        embedding_model: Its pinned embedding model, likewise.
        can_embed: Whether it has an embeddings API.
        max_tokens_option: Its chat model's name for the reply cap.
        temperature: The temperature sent when ``CHAT_TEMPERATURE`` is unset;
            None sends none, leaving the model its own.
        rejected_key: Phrases in its errors that mean the key was refused.
        rate_limited: Phrases in its errors that mean a spent quota or a rate
            limit.
    """

    name: Provider
    title: str
    langchain_name: str
    key_field: str | None = None
    key_variable: str | None = None
    chat_model: str | None = None
    embedding_model: str | None = None
    can_embed: bool = True
    max_tokens_option: str = "max_tokens"
    # None for the hosted providers, whose current models deprecate
    # temperature: ignored by some, refused by others.
    temperature: float | None = None
    rejected_key: tuple[str, ...] = ()
    rate_limited: tuple[str, ...] = ()

    def api_key(self, credentials: Credentials) -> SecretStr | None:
        """Its key, from the settings.

        Args:
            credentials: Chat or embedding settings.

        Returns:
            The key, or None if it is unset or the provider takes none.
        """
        return getattr(credentials, self.key_field) if self.key_field else None

    def chat(self, settings: ChatSettings) -> BaseChatModel:
        """Build its chat model.

        Args:
            settings: The chat settings; ``model`` is set.

        Returns:
            A chat model ready to bind tools to.

        Raises:
            ImportError: Its package is not installed.
        """
        from langchain.chat_models import init_chat_model

        return init_chat_model(settings.model, model_provider=self.langchain_name,
                               **self.chat_options(settings))

    def chat_options(self, settings: ChatSettings) -> dict[str, Any]:
        """The keyword arguments its chat model is built with.

        Args:
            settings: The chat settings.

        Returns:
            The key, temperature and reply cap, each only when set.  Keys are
            passed explicitly: pydantic-settings reads ``.env`` without
            exporting it, so a client reading its own variable would not see
            one set there.
        """
        options: dict[str, Any] = {}
        key = self.api_key(settings)
        if key is not None:
            options["api_key"] = key.get_secret_value()
        if settings.temperature is not None:
            options["temperature"] = settings.temperature
        if settings.max_tokens is not None:
            options[self.max_tokens_option] = settings.max_tokens
        return options

    def embedder(self, settings: EmbeddingSettings) -> Embedder:
        """A function embedding one batch with this provider.

        Args:
            settings: The embedding settings; ``model`` is set.

        Returns:
            The function, holding one client for every batch.

        Raises:
            ImportError: Its package is not installed.
            ValueError: It has no embeddings API.
        """
        raise ValueError(f"{self.title} has no embeddings API")

    def embeddings_name(self, shared: str) -> str:
        """The file its vectors are kept in.

        Args:
            shared: The configured name, ``srd_embeddings.idx``.

        Returns:
            The name with the provider before the suffix
            (``srd_embeddings.ollama.idx``), so switching provider never
            overwrites another's vectors.
        """
        path = Path(shared)
        return path.with_suffix(f".{self.name}{path.suffix}").name

    def explain(self, text: str, settings: ChatSettings) -> str | None:
        """A sentence for a failure only this provider has.

        Args:
            text: The error, as ``Type: message``.
            settings: The chat settings.

        Returns:
            The sentence, or None to leave the error to the generic handling.
        """
        return None


class Google(ModelProvider):
    """Gemini, the default for the chat and the embeddings."""

    name = Provider.GOOGLE
    title = "Google"
    langchain_name = "google_genai"
    key_field = "google_api_key"
    key_variable = "GOOGLE_API_KEY"
    # Pinned: a "-latest" alias changes behaviour without a commit.
    chat_model = "gemini-3.8-flash"
    # A GA id: the shared file's vectors must stay in one space.
    embedding_model = "gemini-embedding-001"
    rejected_key = ("API_KEY_INVALID", "API key not valid")
    rate_limited = ("RESOURCE_EXHAUSTED", "429")

    def embedder(self, settings: EmbeddingSettings) -> Embedder:
        """``google-genai`` directly, for the task type and the width."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key(settings).get_secret_value())
        config = types.EmbedContentConfig(
            task_type=settings.task_type,
            output_dimensionality=settings.dimensions)
        return lambda chunk: [
            item.values for item in client.models.embed_content(
                model=settings.model, contents=chunk, config=config).embeddings]

    def embeddings_name(self, shared: str) -> str:
        """The shared name itself: the distributed file holds Gemini's."""
        return shared


class OpenAI(ModelProvider):
    """OpenAI, or any server speaking its API (``OPENAI_BASE_URL``)."""

    name = Provider.OPENAI
    title = "OpenAI"
    langchain_name = "openai"
    key_field = "openai_api_key"
    key_variable = "OPENAI_API_KEY"
    rejected_key = ("invalid_api_key", "Incorrect API key", "Error code: 401")
    rate_limited = ("insufficient_quota", "rate_limit_exceeded", "429")

    def chat_options(self, settings: ChatSettings) -> dict[str, Any]:
        """Also streamed usage, without which a streamed call reports no
        tokens, and the server's address when one is set."""
        options = super().chat_options(settings) | {"stream_usage": True}
        if settings.openai_base_url:
            options["base_url"] = settings.openai_base_url
        return options

    def embedder(self, settings: EmbeddingSettings) -> Embedder:
        """LangChain's ``OpenAIEmbeddings``, at the configured width."""
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=settings.model, dimensions=settings.dimensions,
            api_key=self.api_key(settings).get_secret_value(),
            base_url=settings.openai_base_url).embed_documents


class Anthropic(ModelProvider):
    """Claude.  Chat only: Anthropic has no embeddings API."""

    name = Provider.ANTHROPIC
    title = "Anthropic"
    langchain_name = "anthropic"
    key_field = "anthropic_api_key"
    key_variable = "ANTHROPIC_API_KEY"
    can_embed = False
    rejected_key = ("authentication_error", "Error code: 401")
    rate_limited = ("rate_limit_error", "429")


class Ollama(ModelProvider):
    """A local Ollama server, which takes no key."""

    name = Provider.OLLAMA
    title = "Ollama"
    langchain_name = "ollama"
    max_tokens_option = "num_predict"
    # Below Ollama's own 0.8, for steadier tool calls from small local models.
    temperature = 0.2
    # From httpx when LangChain calls it, from the ollama client otherwise.
    unreachable = ("Connection refused", "Failed to connect to Ollama")

    def chat_options(self, settings: ChatSettings) -> dict[str, Any]:
        """Also the server's address."""
        return super().chat_options(settings) | {"base_url": settings.ollama_base_url}

    def embedder(self, settings: EmbeddingSettings) -> Embedder:
        """LangChain's ``OllamaEmbeddings``, at the model's own width."""
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(model=settings.model,
                                base_url=settings.ollama_base_url).embed_documents

    def explain(self, text: str, settings: ChatSettings) -> str | None:
        """The server not running, or the model not pulled."""
        if any(sign in text for sign in self.unreachable):
            return (f"Ollama is not reachable at {settings.ollama_base_url}. "
                    "Start it (`ollama serve`) or set OLLAMA_BASE_URL.")
        if "not found" in text:
            return (f"Ollama has no model {settings.model}. Run `ollama pull "
                    f"{settings.model}`.")
        return None


PROVIDERS: dict[Provider, ModelProvider] = {
    provider.name: provider
    for provider in (Google(), OpenAI(), Anthropic(), Ollama())
}
