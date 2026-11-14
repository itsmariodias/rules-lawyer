"""The LangGraph tool-calling agent and its model.  History is in the checkpointer."""

from __future__ import annotations

from functools import lru_cache

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.base import BaseCheckpointSaver

from rules_lawyer.chat import cypher
from rules_lawyer.chat.prompts import prompt
from rules_lawyer.chat.stub import ScriptedModel
from rules_lawyer.chat.tools import TOOLS
from rules_lawyer.config import get_settings

SYSTEM_PROMPT = prompt("system")


class NoApiKey(RuntimeError):
    """``GOOGLE_API_KEY`` is unset and the stub is off."""


def system_prompt() -> str:
    """``system.md`` plus the derived graph schema.

    If the graph is unreachable the schema is omitted rather than failing the
    agent build; the tools then report the outage themselves.  ``build_agent``
    asks again on every call, so the schema is added once the graph is up.

    Returns:
        The full system prompt.
    """
    try:
        return f"{SYSTEM_PROMPT}\n\n{cypher.schema()}"
    except Exception:  # any of the driver's connection failures
        return SYSTEM_PROMPT


def model() -> BaseChatModel:
    """The chat model: Gemini, or ``ScriptedModel`` under ``CHAT_STUB``.

    Returns:
        A chat model ready to bind tools to.

    Raises:
        NoApiKey: ``GOOGLE_API_KEY`` is unset and the stub is off.
    """
    chat = get_settings().chat
    if chat.stub:
        return ScriptedModel()
    if chat.google_api_key is None:
        raise NoApiKey(
            "GOOGLE_API_KEY is not set. Add it to .env and restart the "
            "server.")
    return ChatGoogleGenerativeAI(
        model=chat.model,
        temperature=chat.temperature,
        google_api_key=chat.google_api_key.get_secret_value(),
    )


@lru_cache(maxsize=1)
def compile_agent(checkpointer: BaseCheckpointSaver | None, prompt: str):
    """Compile the agent for a checkpointer and system prompt, caching the last.

    Keyed on the prompt so that an agent compiled while the graph was down
    (no schema) is replaced once the schema can be read.

    Args:
        checkpointer: Where conversation state is stored.
        prompt: The full system prompt.

    Returns:
        A compiled LangGraph agent.

    Raises:
        NoApiKey: See ``model``.
    """
    return create_agent(
        model=model(),
        tools=TOOLS,
        system_prompt=prompt,
        checkpointer=checkpointer,
    )


def build_agent(checkpointer: BaseCheckpointSaver | None = None):
    """The agent for ``checkpointer`` with the current system prompt.

    Args:
        checkpointer: Where conversation state is stored.

    Returns:
        A compiled LangGraph agent, reused while the prompt is unchanged.

    Raises:
        NoApiKey: See ``model``.
    """
    return compile_agent(checkpointer, system_prompt())
