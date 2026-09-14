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

from langchain_core.messages import (AIMessage, AIMessageChunk, HumanMessage,
                                     ToolMessage)
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
                # The tools attach a status and one short line as an
                # artifact, which LangChain carries on the message and never
                # shows the model.  Without it the trace can only say a call
                # finished, so a refused query and a perfect one draw the
                # same grey dot.  A tool that raised rather than returning
                # has no artifact at all, and LangChain marks the message.
                artifact = getattr(message, "artifact", None) or {}
                failed = getattr(message, "status", None) == "error"
                events.append({
                    "type": "tool_end",
                    "id": message.tool_call_id,
                    "name": message.name,
                    "result_chars": len(str(message.content)),
                    "status": ("failed" if failed
                               else artifact.get("status", "ok")),
                    "summary": artifact.get("summary"),
                    "subject": artifact.get("subject"),
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


def _call_row(call: dict) -> dict:
    """One tool call, in the shape ``tool_start`` sends it live."""
    return {"id": call["id"], "name": call["name"],
            "args": call.get("args") or {},
            "done": False, "status": None, "summary": None,
            "subject": None}


def _close_row(row: dict, message: ToolMessage) -> None:
    """The same reading ``tool_end`` takes, from the stored message."""
    artifact = getattr(message, "artifact", None) or {}
    row["done"] = True
    row["status"] = ("failed" if getattr(message, "status", None) == "error"
                     else artifact.get("status", "ok"))
    row["summary"] = artifact.get("summary")
    row["subject"] = artifact.get("subject")


def turns_of(messages: list, when: dict[str, str] | None = None) -> list[dict]:
    """
    A stored conversation, as the turns a UI draws.

    ``when`` maps a message id to the moment it was written, which is the
    checkpoint's own timestamp rather than anything the model said.  Absent,
    every turn is simply undated: a conversation stored before this was read
    is still a conversation.

    Pure, so the part that decides which lookups belong to which turn is
    tested without a database or a model, the way ``neighbourhood.assemble``
    and ``retrieval.fuse`` are.
    """
    when = when or {}
    turns: list[dict] = []
    # Keyed by tool call id, which is what joins a call to its result, and
    # ordered, which is what keeps the trace in the order they were made.
    pending: dict[str, dict] = {}

    for message in messages:
        if isinstance(message, HumanMessage):
            turns.append({"role": "user", "content": message.text,
                          "at": when.get(message.id)})
            # A turn that ended in an error leaves its lookups behind. They
            # belong to that turn, not to the next question.
            pending = {}
        elif isinstance(message, ToolMessage):
            row = pending.get(message.tool_call_id)
            if row is not None:
                _close_row(row, message)
        elif isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                if call.get("id") and call.get("name"):
                    pending[call["id"]] = _call_row(call)
            text = message.text
            if not message.tool_calls and text.strip():
                # Nothing is in flight in a conversation being read back, so
                # a call whose result is missing is finished with an unknown
                # outcome rather than left pulsing for ever.
                tools = [{**row, "done": True} for row in pending.values()]
                turns.append({"role": "assistant", "content": text,
                              "citations": resolve_citations(text),
                              "tools": tools,
                              "at": when.get(message.id)})
                pending = {}
    return turns


def name_missing_subjects(turns: list[dict]) -> list[dict]:
    """
    Name what a stored lookup looked at, where the tool did not say.

    A conversation answered before the tools carried an artifact has only the
    dotted id it was called with, and `11.2.70` names nothing to anyone
    reading the trace.  The graph still knows, and this is the same lookup
    ``resolve_citations`` makes for every citation the answer carries.

    Only the subject is recovered.  A count of what came back cannot be, short
    of running the search again, so those rows stay blank rather than claiming
    a number nobody recorded.
    """
    named: dict[str, str | None] = {}
    for turn in turns:
        for call in turn.get("tools") or []:
            section_id = (call.get("args") or {}).get("section_id")
            if call.get("subject") or not section_id:
                continue
            if section_id not in named:
                found = retrieval.get_section(section_id)
                named[section_id] = found[0].heading if found else None
            call["subject"] = named[section_id]
    return turns


# A stored result is as long as the tool made it, which for a wide query is
# the whole rendered table.  Capped where it is read rather than where it is
# written: the model was given the whole thing, and a reader asking to see
# what the model saw should get the same, up to a length a browser can draw.
RESULT_CHARS = 40_000


def find_result(messages: list, call_id: str) -> dict | None:
    """
    One lookup's stored result, by the id that joins a call to its answer.

    Pure, so the search is tested without a checkpointer.  ``None`` when
    there is no such call in this conversation, which is what the route turns
    into a 404 rather than an empty panel.
    """
    for message in messages:
        if (isinstance(message, ToolMessage)
                and message.tool_call_id == call_id):
            content = str(message.content)
            return {"id": call_id, "name": message.name,
                    "content": content[:RESULT_CHARS],
                    "truncated": len(content) > RESULT_CHARS}
    return None


async def lookup(thread_id: str, call_id: str,
                 checkpointer: BaseCheckpointSaver) -> dict | None:
    """
    What one lookup returned, read back when a reader asks to see it.

    Not sent with the conversation.  One turn of the Frightened question
    stored twenty results and a hundred kilobytes of table, almost none of
    which anyone opens, so the trace carries counts and this fetches the rest
    on demand.  It works for a turn still on screen as well as a reopened
    one: a tool result is checkpointed as soon as its step completes, which
    is before the row it belongs to is drawn as finished.
    """
    agent = build_agent(checkpointer)
    state = await agent.aget_state(_thread(thread_id))
    return find_result((state.values or {}).get("messages", []), call_id)


async def written_at(thread_id: str,
                     checkpointer: BaseCheckpointSaver) -> dict[str, str]:
    """
    When each message in a thread was first written, by its id.

    The checkpointer stamps every step it saves, and a message's own moment
    is the *earliest* checkpoint it appears in: later ones carry it forward
    unchanged.  ``alist`` yields newest first, so overwriting as it goes
    leaves the oldest sighting standing, which is the one wanted.
    """
    when: dict[str, str] = {}
    async for item in checkpointer.alist(_thread(thread_id)):
        stamp = item.checkpoint.get("ts")
        if not stamp:
            continue
        for message in (item.checkpoint.get("channel_values")
                        or {}).get("messages", []):
            message_id = getattr(message, "id", None)
            if message_id:
                when[message_id] = stamp
    return when


async def history(thread_id: str, checkpointer: BaseCheckpointSaver) -> list[dict]:
    """
    The stored turns of one thread, for a UI reopening it after a reload.

    The lookups come back with them.  They used to be dropped here, since the
    only messages this read were the human ones and the final answer, so a
    conversation reopened from the list showed its answers with no retrieval
    under them and the trace read as something that had never happened.
    Everything needed is already in the checkpoint: the tool calls on the
    assistant messages that made them, and the status and summary on the tool
    results that answered them.
    """
    agent = build_agent(checkpointer)
    state = await agent.aget_state(_thread(thread_id))
    return name_missing_subjects(
        turns_of((state.values or {}).get("messages", []),
                 await written_at(thread_id, checkpointer)))


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
