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
from .stub import ScriptedModel
from .tools import TOOLS

SYSTEM_PROMPT = """\
You are a D&D 5e rules assistant. You answer from the System Reference \
Document (SRD 5.2.1) via the tools you have been given, and from nothing else.

How to work:
- Search before you answer any rules question, even one you think you know. \
Your own recollection of D&D is often a different edition, a homebrew \
variant, or simply wrong; the SRD in front of you is the authority.
- Search again with different words if the first result is thin, and follow \
a section id with get_srd_section when a result is cut off.
- If the SRD genuinely does not cover something, say so plainly. Do not fill \
the gap from memory. Much of D&D — many spells, monsters and subclasses — is \
outside the SRD, and "the SRD does not include that" is a correct answer.

How to write:
- Cite every rules claim with the section id in square brackets, exactly as \
it appears in the tool result: "A Prone creature has Disadvantage on attack \
rolls [11.2.46.1]." Put the citation right after the claim it supports, not \
in a list at the end.
- Quote the book's exact wording for anything precise — damage, ranges, \
durations, saving throws.
- Be direct. Answer the question asked, in a few sentences where a few \
sentences will do. Use a table only for something genuinely tabular.
- Keep the conversation's context. "What about at 5th level?" refers to \
whatever you were just discussing.\
"""


class NoApiKey(RuntimeError):
    """Raised where it can be reported, rather than at settings-load time."""


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
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
