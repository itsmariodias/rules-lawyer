"""The chat model the agent and titles are built on."""

from __future__ import annotations

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from rules_lawyer.config import Provider, get_settings

# LangChain's name for each provider.  The extra installing a provider's
# package has the provider's own name (``uv sync --extra ollama``).
LANGCHAIN_PROVIDERS = {
    Provider.GOOGLE: "google_genai",
    Provider.OPENAI: "openai",
    Provider.ANTHROPIC: "anthropic",
    Provider.OLLAMA: "ollama",
}


class ModelUnavailable(RuntimeError):
    """The configured chat model cannot be built: no key, no model or no
    package."""


def model() -> BaseChatModel:
    """The configured chat model.

    Returns:
        A chat model ready to bind tools to.

    Raises:
        ModelUnavailable: The provider's key or ``CHAT_MODEL`` is unset, or
            its package is not installed.
    """
    chat = get_settings().chat
    provider = chat.provider
    variable = chat.missing_key()
    if variable:
        raise ModelUnavailable(
            f"{variable} is not set (CHAT_PROVIDER={provider}). Add it to "
            f".env and restart the server.")
    if chat.model is None:
        raise ModelUnavailable(
            f"CHAT_MODEL is not set (CHAT_PROVIDER={provider}). Add it to "
            f".env and restart the server.")

    options: dict = {}
    key = chat.api_key()
    if key is not None:
        options["api_key"] = key.get_secret_value()
    if chat.temperature is not None:
        options["temperature"] = chat.temperature
    if chat.max_tokens is not None:
        # Ollama's name for the same cap.
        name = "num_predict" if provider is Provider.OLLAMA else "max_tokens"
        options[name] = chat.max_tokens
    if provider is Provider.OPENAI:
        # Without it a streamed call reports no token usage.
        options["stream_usage"] = True
        if chat.openai_base_url:
            options["base_url"] = chat.openai_base_url
    if provider is Provider.OLLAMA:
        options["base_url"] = chat.ollama_base_url

    try:
        return init_chat_model(chat.model,
                               model_provider=LANGCHAIN_PROVIDERS[provider],
                               **options)
    except ImportError as exc:
        raise ModelUnavailable(
            f"CHAT_PROVIDER={provider} needs its package: run "
            f"`uv sync --extra {provider}` in backend/ and restart the "
            f"server.") from exc
