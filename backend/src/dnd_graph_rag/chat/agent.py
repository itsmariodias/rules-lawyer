"""
The LangGraph tool-calling agent, and the model it runs on.

The agent itself is stateless: history lives in the checkpointer that
``api.lifespan`` opens and passes in, addressed by a thread id the caller
holds, so conversations survive a restart.
"""

from __future__ import annotations

from functools import lru_cache

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.base import BaseCheckpointSaver

from ..config import get_settings
from . import cypher
from .prompts import prompt
from .stub import ScriptedModel
from .tools import TOOLS

# What the agent is told before every turn; read and edit it as markdown.
SYSTEM_PROMPT = prompt("system")


class NoApiKey(RuntimeError):
    """Raised where it can be reported, rather than at settings-load time."""


def system_prompt() -> str:
    """
    The prompt, plus the schema the Cypher tool is written against.

    The schema is read off the loaded graph rather than written down here,
    and it is in the *prompt* rather than behind a tool of its own: the model
    has to know the labels at the moment it composes a query, and discovering
    them costs a round trip on every turn that touches the graph and two on
    every turn that guesses wrong.

    A graph that cannot be reached costs the schema, not the turn.  The tools
    will fail with their own message, which is the honest thing for a chat
    whose database is down to say — and much better than a 503 from
    ``build_agent`` on a question the model could have answered.
    """
    try:
        return f"{SYSTEM_PROMPT}\n\n{cypher.schema()}"
    except Exception:  # any of the driver's connection failures
        return SYSTEM_PROMPT


def model() -> BaseChatModel:
    """
    The model the agent runs on.  There is one, and it is required.

    ``CHAT_STUB`` swaps in the scripted model the suites drive; it is never
    reached by a failure, which is the whole difference between a test seam
    and a fallback.
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
def build_agent(checkpointer: BaseCheckpointSaver | None = None):
    """
    The compiled agent, cached per checkpointer.

    The server creates one checkpointer, so this builds one graph per
    process; a test passing its own saver gets its own agent.
    """
    return create_agent(
        model=model(),
        tools=TOOLS,
        system_prompt=system_prompt(),
        checkpointer=checkpointer,
    )
