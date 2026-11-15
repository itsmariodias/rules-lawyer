"""The chat model the agent and titles are built on."""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from rules_lawyer.config import get_settings


class NoApiKey(RuntimeError):
    """``GOOGLE_API_KEY`` is unset."""


def model() -> BaseChatModel:
    """The configured chat model.

    Returns:
        A chat model ready to bind tools to.

    Raises:
        NoApiKey: ``GOOGLE_API_KEY`` is unset.
    """
    chat = get_settings().chat
    if chat.google_api_key is None:
        raise NoApiKey(
            "GOOGLE_API_KEY is not set. Add it to .env and restart the "
            "server.")
    return ChatGoogleGenerativeAI(
        model=chat.model,
        temperature=chat.temperature,
        google_api_key=chat.google_api_key.get_secret_value(),
    )
