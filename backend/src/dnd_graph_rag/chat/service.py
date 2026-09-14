"""
One turn of conversation, as a flat stream of typed events.

LangGraph streams messages, chunks and state updates; this flattens them
into ``token``, ``tool_start``, ``tool_end``, ``citations``, ``error`` and
``done``, which a browser can render as they arrive.  Nothing here knows
about HTTP: ``chat.routes`` encodes the dicts as SSE, and a test
iterates them directly.

It also owns what a thread *is*: listing, reading back, pinning and deleting
conversations, all of which live in the checkpointer and its store.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from ..config import get_settings
from . import retrieval
from .agent import build_agent

# A citation as the prompt asks for it: a dotted id in square brackets.
# Anchored on the digits so prose brackets — "[see below]" — never match.
CITATION = re.compile(r"\[(\d+(?:\.\d+)+)\]")


def _thread(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def resolve_citations(text: str) -> list[dict]:
    """
    Turn the ids the model wrote into citations the UI can open.

    Driven by the finished answer rather than by what was retrieved, so the
    list is what the answer leans on, and an id the model invented resolves
    to nothing and is dropped instead of rendering as a dead chip.
    """
    seen: list[str] = []
    for match in CITATION.findall(text):
        if match not in seen:
            seen.append(match)

    citations = []
    for section_id in seen:
        found = retrieval.get_section(section_id)
        if found is not None:
            citations.append(found[0].as_citation())
    return citations


async def stream_turn(message: str, thread_id: str,
                      checkpointer: BaseCheckpointSaver) -> AsyncIterator[dict]:
    """
    Run one user message and yield events until the answer is complete.

    History is not passed in: the checkpointer holds it under ``thread_id``,
    so a caller only ever sends the new message.

    The model is required.  Nothing answers in its place, so a call that
    cannot be made or cannot be finished ends the turn with an ``error``
    saying which.
    """
    config = _thread(thread_id)
    answer: list[str] = []
    announced: set[str] = set()

    try:
        agent = build_agent(checkpointer)
        stream = agent.astream(
            {"messages": [HumanMessage(content=message)]},
            config=config,
            stream_mode=["messages", "updates"],
        )
        async for mode, payload in _until_silent(
                stream, get_settings().chat.timeout_seconds):
            if mode == "messages":
                chunk, _ = payload
                for event in _from_message_chunk(chunk, answer, announced):
                    yield event
            elif mode == "updates":
                for event in _from_update(payload):
                    yield event
    # The error is the reply: it reaches the browser as an event rather than
    # as a stream that simply stops, and it is the last thing said on this
    # turn.  A part-written answer keeps what it managed to say, above it.
    except Exception as exc:
        yield {"type": "error", "message": _explain(exc)}

    text = "".join(answer)
    # No answer, no citations: an empty list after an error would read as
    # "nothing to cite" rather than as "nothing was said".
    if text.strip():
        yield {"type": "citations", "citations": resolve_citations(text)}
    yield {"type": "done", "thread_id": thread_id}


async def _until_silent(stream: AsyncIterator, seconds: float) -> AsyncIterator:
    """
    The agent's own stream, failed after *seconds* of silence.

    Not a limit on how long an answer may take — every token and every tool
    result resets it.  A stalled call never yields and never raises, so
    without this the turn hangs with no answer and no error.
    """
    events = stream.__aiter__()
    while True:
        try:
            yield await asyncio.wait_for(events.__anext__(), seconds)
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"the model sent nothing for {seconds:g}s") from exc


# A provider error is JSON with the sentence buried in it — the invalid-key
# one runs to 600 characters — and the error is what the reader gets instead
# of an answer, so anything unrecognised is capped at a readable length.
ERROR_CHARS = 220


def _explain(exc: Exception) -> str:
    """
    A provider error as a sentence the reader can act on.

    The three that actually happen — no key, a rejected key, a spent quota —
    are named; pydantic and Google both bury them several lines deep.
    """
    text = f"{type(exc).__name__}: {exc}"
    if "GOOGLE_API_KEY" in text:
        return ("GOOGLE_API_KEY is not set. Add it to .env and restart "
                "the server.")
    if "API_KEY_INVALID" in text or "API key not valid" in text:
        return ("GOOGLE_API_KEY was rejected by Google. Check the key in "
                ".env and restart the server.")
    if "RESOURCE_EXHAUSTED" in text or "429" in text:
        return ("The Gemini quota is spent — the free tier allows a limited "
                "number of requests per day, per model.")
    if isinstance(exc, TimeoutError):
        return (f"The model stopped responding ({exc}). Nothing arrived, so "
                "the turn was ended rather than left hanging.")
    if len(text) <= ERROR_CHARS:
        return text
    return text[:ERROR_CHARS].rsplit(" ", 1)[0] + "…"


def _from_message_chunk(chunk: Any, answer: list[str],
                        announced: set[str]) -> list[dict]:
    """
    Token deltas, plus tool calls the moment their arguments finish streaming.

    Gemini streams a tool call's arguments across chunks, so the call is
    announced only once ``id`` and ``name`` are both present, and ``announced``
    keeps a re-sent chunk from drawing the same trace line twice.
    """
    if not isinstance(chunk, AIMessageChunk):
        return []

    events: list[dict] = []
    for call in chunk.tool_calls or []:
        call_id = call.get("id")
        if call_id and call_id not in announced and call.get("name"):
            announced.add(call_id)
            events.append({"type": "tool_start", "id": call_id,
                           "name": call["name"], "args": call.get("args") or {}})

    text = _text_of(chunk)
    if text:
        answer.append(text)
        events.append({"type": "token", "text": text})
    return events


def _from_update(payload: dict) -> list[dict]:
    """Tool results, read off the state update the tool node writes."""
    events = []
    for messages in (step.get("messages", []) for step in payload.values()
                     if isinstance(step, dict)):
        for message in messages:
            if getattr(message, "type", None) == "tool":
                events.append({
                    "type": "tool_end",
                    "id": message.tool_call_id,
                    "name": message.name,
                    "result_chars": len(str(message.content)),
                })
    return events


def _text_of(chunk: Any) -> str:
    """
    Gemini sends content as a string sometimes and a list of parts others.

    A tool call arrives as a part too, so parts are filtered to text rather
    than joined blindly — otherwise a function call is rendered as prose.
    """
    content = chunk.content
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content
                   if isinstance(part, dict) and part.get("type") == "text")


async def history(thread_id: str, checkpointer: BaseCheckpointSaver) -> list[dict]:
    """The stored turns of one thread, for a UI reopening it after a reload."""
    agent = build_agent(checkpointer)
    state = await agent.aget_state(_thread(thread_id))
    messages = (state.values or {}).get("messages", [])

    turns = []
    for message in messages:
        if isinstance(message, HumanMessage):
            turns.append({"role": "user", "content": message.text})
        elif isinstance(message, AIMessage) and not message.tool_calls:
            text = message.text
            if text.strip():
                turns.append({"role": "assistant", "content": text,
                              "citations": resolve_citations(text)})
    return turns


# The namespace pins live under, in the store beside the checkpointer.
PINS = ("threads", "pinned")


async def pinned(store: BaseStore | None) -> set[str]:
    """The pinned thread ids. Empty when there is no store to ask."""
    if store is None:
        return set()
    return {item.key for item in await store.asearch(PINS)}


async def set_pinned(store: BaseStore, thread_id: str, pin: bool) -> None:
    """
    Pin or unpin one conversation.

    Unpinning deletes the row rather than writing ``false``: the value
    carries nothing the key does not.
    """
    if pin:
        await store.aput(PINS, thread_id, {"pinned": True})
    else:
        await store.adelete(PINS, thread_id)


async def threads(checkpointer: BaseCheckpointSaver,
                  store: BaseStore | None = None,
                  limit: int = 50) -> list[dict]:
    """
    Every conversation on disk, pinned first and newest first within that.

    Checkpoints are written per step and arrive newest first, so the first
    one seen for a thread is its latest.  Pins are merged here rather than in
    the route, so one place decides both what the list holds and its order.
    """
    pins = await pinned(store)
    found: dict[str, dict] = {}
    async for item in checkpointer.alist(None, limit=limit * 40):
        thread_id = item.config["configurable"]["thread_id"]
        if thread_id in found:
            continue
        messages = (item.checkpoint.get("channel_values") or {}).get("messages", [])
        opening = next((m for m in messages if isinstance(m, HumanMessage)), None)
        if opening is None:
            continue  # a thread whose first step is checkpointed before input
        found[thread_id] = {
            "thread_id": thread_id,
            "title": _title(opening.text),
            "updated_at": item.checkpoint.get("ts"),
            "messages": sum(1 for m in messages if isinstance(m, HumanMessage)),
            "pinned": thread_id in pins,
        }
    return sorted(found.values(),
                  key=lambda t: (t["pinned"], t["updated_at"] or ""),
                  reverse=True)[:limit]


async def forget(thread_id: str, checkpointer: BaseCheckpointSaver,
                 store: BaseStore | None = None) -> bool:
    """
    Drop one conversation and everything checkpointed under it.

    There is no thread table, so dropping the checkpoints drops the thread.
    Returns whether there was anything there, so the route can answer 404 for
    an id nobody ever used.
    """
    if await checkpointer.aget_tuple(_thread(thread_id)) is None:
        return False
    await checkpointer.adelete_thread(thread_id)
    if store is not None:
        # Otherwise the pin is a row nothing reads and nothing cleans up.
        await store.adelete(PINS, thread_id)
    return True


def _title(text: str, limit: int = 60) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit].rsplit(" ", 1)[0] + "…"
