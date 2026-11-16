"""The chat model the agent and titles are built on."""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from rules_lawyer.config import get_settings


class ModelUnavailable(RuntimeError):
    """The configured chat model cannot be built: no key, no model or no
    package."""


def model() -> BaseChatModel:
    """The configured chat model, built by its provider.

    Returns:
        A chat model ready to bind tools to.

    Raises:
        ModelUnavailable: The provider's key or ``CHAT_MODEL`` is unset, or
            its package is not installed.
    """
    chat = get_settings().chat
    variable = chat.missing_key()
    if variable:
        raise ModelUnavailable(
            f"{variable} is not set (CHAT_PROVIDER={chat.provider}). Add it "
            f"to .env and restart the server.")
    if chat.model is None:
        raise ModelUnavailable(
            f"CHAT_MODEL is not set (CHAT_PROVIDER={chat.provider}). Add it "
            f"to .env and restart the server.")
    try:
        return chat.model_provider.chat(chat)
    except ImportError as exc:
        raise ModelUnavailable(
            f"CHAT_PROVIDER={chat.provider} needs its package: run "
            f"`uv sync --extra {chat.provider}` in backend/ and restart the "
            f"server.") from exc
