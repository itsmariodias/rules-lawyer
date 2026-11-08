"""
What a conversation is called in the thread list.

The opening question cut to a line made every title in a 260px list read as
"What does the Prone conditio…", so six conversations about Prone looked
like one. A new conversation is now titled by a summary of its first
question, a few words long, written once by the model while the first answer
is being written and stored beside the pins.

A title is a label rather than an answer, so a failure to write one is not
an error: the list falls back to the cut question, which is what it showed
before and is still true. That is also what every conversation from before
titles existed shows, and what the suites see under ``CHAT_STUB``.
"""

from __future__ import annotations

import asyncio
import logging
import re

from langgraph.store.base import BaseStore

from ..config import get_settings
from . import agent

log = logging.getLogger(__name__)

# The namespace titles live under, beside the pins.
TITLES = ("threads", "title")
# Past this a title is a sentence, and the list truncates it anyway.
WORDS = 5
# A label is not worth holding a turn's stream open for.
TIMEOUT_SECONDS = 10.0
# ``asearch`` defaults to ten, which would quietly title the eleventh
# conversation by its question.
EVERY = 10_000

PROMPT = (
    "Write a title of at most five words for a conversation that opens with "
    "the question below. Every conversation here is about the D&D rules, so "
    "do not say D&D, rules or 5e: name the subject, not the fact that it is "
    "a question. Reply with the title only, with no quotes and no full "
    "stop.\n\nQuestion: {question}"
)


def clean(raw: str) -> str | None:
    """
    The model's reply as a title, or ``None`` when nothing usable is left.

    Asked for the title only, a model still sometimes quotes it, bolds it,
    labels it or ends it with a full stop, and occasionally adds a second
    line explaining itself. Only the first line counts.
    """
    line = next((part for part in raw.splitlines() if part.strip()), "")
    line = re.sub(r"^\s*title\s*:\s*", "", line, flags=re.IGNORECASE)
    line = line.strip().strip("*_#`\"'“”‘’ ").rstrip(".!?:;,")
    words = line.split()
    return " ".join(words[:WORDS]) or None


async def summarise(question: str) -> str | None:
    """
    A title for a conversation that opens with ``question``.

    ``None`` under the stub, without a key, past the timeout or on any
    failure of the model: the caller falls back to the question itself.
    """
    if get_settings().chat.stub:
        return None
    try:
        model = agent.model()
        reply = await asyncio.wait_for(
            model.ainvoke(PROMPT.format(question=question)), TIMEOUT_SECONDS)
    except agent.NoApiKey:
        return None
    except Exception as exc:  # a label is not worth failing a turn over
        log.warning("Could not title a conversation: %s", exc)
        return None
    return clean(reply.text)


async def remember(store: BaseStore, thread_id: str, title: str) -> None:
    await store.aput(TITLES, thread_id, {"title": title})


async def forget(store: BaseStore, thread_id: str) -> None:
    await store.adelete(TITLES, thread_id)


async def titled(store: BaseStore | None) -> dict[str, str]:
    """Every stored title, by thread id. Empty when there is no store."""
    if store is None:
        return {}
    return {item.key: item.value["title"]
            for item in await store.asearch(TITLES, limit=EVERY)}
