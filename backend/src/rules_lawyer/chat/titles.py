"""
Model-written conversation titles, stored beside the pins.

Best effort: on any failure ``threads()`` falls back to the cut opening
question.
"""

from __future__ import annotations

import asyncio
import logging
import re

from langgraph.store.base import BaseStore

from rules_lawyer.chat import agent
from rules_lawyer.chat.prompts import prompt
from rules_lawyer.config import get_settings

log = logging.getLogger(__name__)

TITLES = ("threads", "title")
WORDS = 5
TIMEOUT_SECONDS = 10.0
# ``BaseStore.asearch`` returns only ten results by default.
EVERY = 10_000

PROMPT = prompt("title")


def clean(raw: str) -> str | None:
    """
    Normalise a model's title reply.

    Args:
        raw: The reply text.

    Returns:
        Its first non-blank line without a ``Title:`` label, quotes,
        markdown or trailing punctuation, cut to ``WORDS`` words; None if
        nothing is left.
    """
    line = next((part for part in raw.splitlines() if part.strip()), "")
    line = re.sub(r"^\s*title\s*:\s*", "", line, flags=re.IGNORECASE)
    line = line.strip().strip("*_#`\"'“”‘’ ").rstrip(".!?:;,")
    words = line.split()
    return " ".join(words[:WORDS]) or None


async def summarise(question: str) -> str | None:
    """
    Ask the model for a short title.  Never raises.

    Args:
        question: The conversation's first question.

    Returns:
        The cleaned title, or None under the stub, without a key, after
        ``TIMEOUT_SECONDS``, or on any model error.
    """
    if get_settings().chat.stub:
        return None
    try:
        model = agent.model()
        reply = await asyncio.wait_for(
            model.ainvoke(PROMPT.format(question=question)), TIMEOUT_SECONDS)
    except agent.NoApiKey:
        return None
    except Exception as exc:
        log.warning("Could not title a conversation: %s", exc)
        return None
    return clean(reply.text)


async def remember(store: BaseStore, thread_id: str, title: str) -> None:
    """Store a thread's title."""
    await store.aput(TITLES, thread_id, {"title": title})


async def forget(store: BaseStore, thread_id: str) -> None:
    """Delete a thread's title."""
    await store.adelete(TITLES, thread_id)


async def titled(store: BaseStore | None) -> dict[str, str]:
    """Thread id to title; empty without a store."""
    if store is None:
        return {}
    return {item.key: item.value["title"]
            for item in await store.asearch(TITLES, limit=EVERY)}
