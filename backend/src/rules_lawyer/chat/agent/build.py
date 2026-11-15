"""The LangGraph tool-calling agent.  History is in the checkpointer."""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver

from rules_lawyer.chat.agent.prompts import prompt
from rules_lawyer.chat.agent.tools import TOOLS
from rules_lawyer.chat.retrieval import cypher

SYSTEM_PROMPT = prompt("system")


def system_prompt() -> str:
    """``system.md`` plus the derived graph schema.

    If the graph is unreachable the schema is omitted rather than failing the
    agent build; the tools then report the outage themselves.

    Returns:
        The full system prompt.
    """
    try:
        return f"{SYSTEM_PROMPT}\n\n{cypher.schema()}"
    except Exception:  # noqa: BLE001 - any of the driver's connection failures
        return SYSTEM_PROMPT


def build_agent(model: BaseChatModel,
                checkpointer: BaseCheckpointSaver | None = None):
    """Compile the agent for one turn, with the current system prompt.

    Compiled per turn, not cached: it costs about 2ms, and the prompt then
    gains the graph schema as soon as the graph is reachable.

    Args:
        model: The chat model that answers.
        checkpointer: Where conversation state is stored.

    Returns:
        A compiled LangGraph agent.
    """
    return create_agent(
        model=model,
        tools=TOOLS,
        system_prompt=system_prompt(),
        checkpointer=checkpointer,
    )
