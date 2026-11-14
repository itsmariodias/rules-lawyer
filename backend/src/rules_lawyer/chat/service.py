"""Chat turns as typed event streams, and thread storage operations.

``stream_turn`` yields ``token``, ``tool_start``, ``tool_end``, ``usage``,
``citations``, ``error`` and ``done`` dicts; ``chat.routes`` encodes them as
SSE.  The rest lists, reads back, rewinds, pins and deletes threads in the
checkpointer and store.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from rules_lawyer.chat import retrieval, titles
from rules_lawyer.chat.agent import build_agent
from rules_lawyer.config import get_settings


def _thread(thread_id: str, checkpoint_id: str | None = None) -> dict:
    """LangGraph run config for a thread, optionally branching from a
    checkpoint (used by retry).
    """
    configurable = {"thread_id": thread_id}
    if checkpoint_id is not None:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


def resolve_citations(text: str) -> list[dict]:
    """Look up every section id cited in an answer.

    Args:
        text: The model's answer.

    Returns:
        ``Passage.as_citation()`` per distinct id, in order of first
        appearance.  Ids that match no section are dropped.
    """
    seen: list[str] = []
    for match in retrieval.CITATION.findall(text):
        if match not in seen:
            seen.append(match)

    citations = []
    for section_id in seen:
        found = retrieval.get_section(section_id)
        if found is not None:
            citations.append(found[0].as_citation())
    return citations


async def stream_turn(message: str, thread_id: str,
                      checkpointer: BaseCheckpointSaver,
                      checkpoint_id: str | None = None) -> AsyncIterator[dict]:
    """Run one user message and yield events until the turn ends.

    Never raises: any failure becomes an ``error`` event, followed by
    ``usage`` (if any calls were made) and ``done``.

    Args:
        message: The user's message.
        thread_id: Conversation id; history comes from the checkpointer.
        checkpointer: Conversation storage.
        checkpoint_id: Branch from this checkpoint instead of the latest
            (see ``rewind``).

    Yields:
        Event dicts, ending with ``{"type": "done", "thread_id"}``.
    """
    config = _thread(thread_id, checkpoint_id)
    answer: list[str] = []
    announced: set[str] = set()
    spoken: list[AIMessage] = []

    try:
        # Building the agent reads the graph schema, a synchronous query.
        agent = await asyncio.to_thread(build_agent, checkpointer)
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
                spoken.extend(_model_messages(payload))
                for event in _from_update(payload):
                    yield event
    except Exception as exc:
        yield {"type": "error", "message": _explain(exc)}

    # Sent after an error too; the calls were still billed.
    usage = usage_of(spoken)
    if usage is not None:
        yield {"type": "usage", **usage}

    text = "".join(answer)
    if text.strip():
        yield {"type": "citations",
               "citations": await asyncio.to_thread(resolve_citations, text)}
    yield {"type": "done", "thread_id": thread_id}


async def _until_silent(stream: AsyncIterator, seconds: float) -> AsyncIterator:
    """Re-yield a stream, failing if any gap between items exceeds ``seconds``.

    A stalled model call neither yields nor raises.

    Raises:
        TimeoutError: Nothing arrived for ``seconds``.
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


# Unrecognised provider errors are JSON blobs (the invalid-key one is 600
# characters), so they are cut to this.
ERROR_CHARS = 220


def _explain(exc: Exception) -> str:
    """An exception as a short sentence for the reader.

    Missing key, rejected key, spent quota and silence get fixed messages;
    anything else is truncated to ``ERROR_CHARS``.
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
    """``token`` events for text, and one ``tool_start`` per tool call.

    A call is announced once it has both ``id`` and ``name``; ``announced``
    dedupes across chunks.  Text is also appended to ``answer``.
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


def _outcome(message: ToolMessage) -> dict:
    """A tool result's ``status``, ``summary`` and ``subject``, live or stored."""
    # A tool that raised has no artifact; LangChain sets status="error" on its
    # message instead.
    artifact = getattr(message, "artifact", None) or {}
    failed = getattr(message, "status", None) == "error"
    return {"status": "failed" if failed else artifact.get("status", "ok"),
            "summary": artifact.get("summary"),
            "subject": artifact.get("subject")}


def _from_update(payload: dict) -> list[dict]:
    """``tool_end`` events for the tool results in a state update."""
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
                    **_outcome(message),
                })
    return events


def _model_messages(payload: dict) -> list[AIMessage]:
    """The finished message of each model call in a state update."""
    return [message
            for step in payload.values() if isinstance(step, dict)
            for message in step.get("messages", [])
            if isinstance(message, AIMessage)]


def usage_of(messages: list) -> dict | None:
    """Token usage summed over a turn's model calls.

    Args:
        messages: Any messages; only ``AIMessage.usage_metadata`` is read.

    Returns:
        ``{"input", "output", "total", "calls"}``, or None if no message
        has usage metadata.
    """
    counted = [message.usage_metadata for message in messages
               if isinstance(message, AIMessage) and message.usage_metadata]
    if not counted:
        return None
    return {
        "input": sum(usage.get("input_tokens", 0) for usage in counted),
        "output": sum(usage.get("output_tokens", 0) for usage in counted),
        "total": sum(usage.get("total_tokens", 0) for usage in counted),
        "calls": len(counted),
    }


def _text_of(chunk: Any) -> str:
    """The text of a chunk whose content is a string or a list of parts.

    Non-text parts (e.g. function calls) are skipped.
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
    """Mark a trace row done with its stored result's outcome."""
    row["done"] = True
    row.update(_outcome(message))


def turns_of(messages: list, when: dict[str, str] | None = None) -> list[dict]:
    """A stored conversation as UI turns.

    Tool calls attach to the assistant answer that follows them.  Calls from
    a turn that ended without an answer are discarded at the next question.

    Args:
        messages: The thread's messages, in order.
        when: Message id to ISO timestamp, from ``written_at``.

    Returns:
        ``{"role": "user", "content", "at"}`` and ``{"role": "assistant",
        "content", "citations", "tools", "usage", "at"}`` dicts.
    """
    when = when or {}
    turns: list[dict] = []
    # Tool call id -> trace row, in call order.
    pending: dict[str, dict] = {}
    spoken: list[AIMessage] = []

    for message in messages:
        if isinstance(message, HumanMessage):
            turns.append({"role": "user", "content": message.text,
                          "at": when.get(message.id)})
            pending = {}
            spoken = []
        elif isinstance(message, ToolMessage):
            row = pending.get(message.tool_call_id)
            if row is not None:
                _close_row(row, message)
        elif isinstance(message, AIMessage):
            spoken.append(message)
            for call in message.tool_calls or []:
                if call.get("id") and call.get("name"):
                    pending[call["id"]] = _call_row(call)
            text = message.text
            if not message.tool_calls and text.strip():
                # A call with no stored result is shown done, status unknown.
                tools = [{**row, "done": True} for row in pending.values()]
                turns.append({"role": "assistant", "content": text,
                              "citations": resolve_citations(text),
                              "tools": tools,
                              "usage": usage_of(spoken),
                              "at": when.get(message.id)})
                pending = {}
                spoken = []
    return turns


def name_missing_subjects(turns: list[dict]) -> list[dict]:
    """Fill ``subject`` on stored tool calls that have only a ``section_id``.

    Threads from before tools returned artifacts lack it.

    Args:
        turns: Output of ``turns_of``; mutated.

    Returns:
        ``turns``.
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


# Cap on a stored tool result returned to the browser.
RESULT_CHARS = 40_000


def find_result(messages: list, call_id: str) -> dict | None:
    """One tool call's stored result.

    Args:
        messages: The thread's messages.
        call_id: The tool call id.

    Returns:
        ``{"id", "name", "content", "truncated"}``, or None if the thread has
        no result for that call.
    """
    for message in messages:
        if (isinstance(message, ToolMessage)
                and message.tool_call_id == call_id):
            content = str(message.content)
            return {"id": call_id, "name": message.name,
                    "content": content[:RESULT_CHARS],
                    "truncated": len(content) > RESULT_CHARS}
    return None


def _checkpointed(checkpoint: dict) -> list:
    """The messages stored in one checkpoint."""
    return (checkpoint.get("channel_values") or {}).get("messages", [])


async def _messages(thread_id: str,
                    checkpointer: BaseCheckpointSaver) -> list:
    """A thread's messages, read from storage without building the agent.

    Building it needs a model, and so an API key; reading a stored thread
    needs neither.  Tool results already written by a step still running are
    included, as ``aget_state`` includes them.

    Args:
        thread_id: The thread.
        checkpointer: Conversation storage.

    Returns:
        The messages in order; empty for an unknown thread.
    """
    saved = await checkpointer.aget_tuple(_thread(thread_id))
    if saved is None:
        return []
    messages = list(_checkpointed(saved.checkpoint))
    stored = {message.id for message in messages if message.id}
    for _, channel, value in saved.pending_writes or []:
        if channel != "messages":
            continue
        for message in value if isinstance(value, list) else [value]:
            if not message.id or message.id not in stored:
                messages.append(message)
    return messages


async def lookup(thread_id: str, call_id: str,
                 checkpointer: BaseCheckpointSaver) -> dict | None:
    """One tool call's stored result, read from the thread's latest state.

    Each result is stored as its tool finishes, so this also works while the
    turn is still streaming.

    Args:
        thread_id: The conversation the call was made in.
        call_id: The tool call's id.
        checkpointer: Conversation storage.

    Returns:
        See ``find_result``.
    """
    return find_result(await _messages(thread_id, checkpointer), call_id)


async def written_at(thread_id: str,
                     checkpointer: BaseCheckpointSaver) -> dict[str, str]:
    """Message id to the timestamp of the earliest checkpoint containing it.

    ``alist`` yields newest first, so the last write per id is the earliest.

    Args:
        thread_id: The conversation.
        checkpointer: Conversation storage.

    Returns:
        Message id to ISO timestamp, for every message with an id.
    """
    when: dict[str, str] = {}
    async for item in checkpointer.alist(_thread(thread_id)):
        stamp = item.checkpoint.get("ts")
        if not stamp:
            continue
        for message in _checkpointed(item.checkpoint):
            message_id = getattr(message, "id", None)
            if message_id:
                when[message_id] = stamp
    return when


async def history(thread_id: str, checkpointer: BaseCheckpointSaver) -> list[dict]:
    """One thread's turns, with tool traces, timestamps and usage.

    Args:
        thread_id: The conversation.
        checkpointer: Conversation storage.

    Returns:
        See ``turns_of``; empty for an unknown thread.
    """
    messages = await _messages(thread_id, checkpointer)
    when = await written_at(thread_id, checkpointer)
    # Both resolve section ids with synchronous graph queries.
    return await asyncio.to_thread(
        lambda: name_missing_subjects(turns_of(messages, when)))


def last_question(messages: list) -> tuple[str, str] | None:
    """The last human message.

    Args:
        messages: A thread's messages, in order.

    Returns:
        ``(text, message_id)``, or None if there is none.
    """
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message.text, message.id
    return None


async def rewind(thread_id: str,
                 checkpointer: BaseCheckpointSaver) -> tuple[str, str | None] | None:
    """Find where to re-ask the last question from.

    The checkpointer cannot delete one checkpoint, so a retry branches from
    the newest checkpoint without the last question; later ones stay on disk,
    unreachable.  If no such checkpoint exists, the thread's checkpoints are
    deleted so it restarts under the same id.

    Args:
        thread_id: The conversation.
        checkpointer: Conversation storage.

    Returns:
        ``(question, checkpoint_id)``, where a None checkpoint means start
        fresh; or None if the thread has no question.
    """
    asked = last_question(await _messages(thread_id, checkpointer))
    if asked is None:
        return None
    text, message_id = asked

    # Newest first.
    async for item in checkpointer.alist(_thread(thread_id)):
        messages = _checkpointed(item.checkpoint)
        if not any(getattr(m, "id", None) == message_id for m in messages):
            return text, item.config["configurable"]["checkpoint_id"]

    await checkpointer.adelete_thread(thread_id)
    return text, None


PINS = ("threads", "pinned")


async def pinned(store: BaseStore | None) -> set[str]:
    """The pinned thread ids.

    Args:
        store: Pins and titles, or None.

    Returns:
        The ids; empty without a store.
    """
    if store is None:
        return set()
    # ``asearch`` defaults to ten, which silently unpinned the eleventh.
    return {item.key for item in await store.asearch(PINS, limit=titles.EVERY)}


async def set_pinned(store: BaseStore, thread_id: str, pin: bool) -> None:
    """Pin a thread, or unpin it by deleting its row.

    Args:
        store: Pins and titles.
        thread_id: The conversation.
        pin: True to pin, False to unpin.
    """
    if pin:
        await store.aput(PINS, thread_id, {"pinned": True})
    else:
        await store.adelete(PINS, thread_id)


# Checkpoints scanned per thread listed.  One turn writes one per step, and
# a turn of 20 lookups writes over 40, so older threads fall outside the
# scan; pinned threads are fetched by id instead.
CHECKPOINTS_PER_THREAD = 40


async def threads(checkpointer: BaseCheckpointSaver,
                  store: BaseStore | None = None,
                  limit: int = 50) -> list[dict]:
    """Stored threads, pinned first, then most recently updated.

    Args:
        checkpointer: Conversation storage.
        store: Pins and titles; optional.
        limit: Maximum unpinned threads returned.  Every pinned thread is
            returned, however old.

    Returns:
        ``{"thread_id", "title", "updated_at", "messages", "pinned"}`` per
        thread.  The title falls back to the cut opening question.
    """
    pins = await pinned(store)
    named = await titles.titled(store)
    # Thread id -> its newest checkpoint; ``alist`` yields newest first.
    newest: dict[str, dict] = {}
    async for item in checkpointer.alist(
            None, limit=limit * CHECKPOINTS_PER_THREAD):
        newest.setdefault(item.config["configurable"]["thread_id"],
                          item.checkpoint)
    for thread_id in pins - newest.keys():
        saved = await checkpointer.aget_tuple(_thread(thread_id))
        if saved is not None:
            newest[thread_id] = saved.checkpoint

    listed: list[dict] = []
    for thread_id, checkpoint in newest.items():
        messages = _checkpointed(checkpoint)
        questions = [m for m in messages if isinstance(m, HumanMessage)]
        if not questions:
            continue  # only the pre-input checkpoint so far
        listed.append({
            "thread_id": thread_id,
            "title": named.get(thread_id) or _title(questions[0].text),
            "updated_at": checkpoint.get("ts"),
            "messages": len(questions),
            "pinned": thread_id in pins,
        })
    listed.sort(key=lambda t: t["updated_at"] or "", reverse=True)
    pinned_first = [t for t in listed if t["pinned"]]
    return pinned_first + [t for t in listed if not t["pinned"]][:limit]


async def forget(thread_id: str, checkpointer: BaseCheckpointSaver,
                 store: BaseStore | None = None) -> bool:
    """Delete a thread's checkpoints, pin and title.

    Args:
        thread_id: The conversation.
        checkpointer: Conversation storage.
        store: Pins and titles, or None to delete the checkpoints alone.

    Returns:
        False if the thread had no checkpoints.
    """
    if await checkpointer.aget_tuple(_thread(thread_id)) is None:
        return False
    await checkpointer.adelete_thread(thread_id)
    if store is not None:
        await store.adelete(PINS, thread_id)
        await titles.forget(store, thread_id)
    return True


def _title(text: str, limit: int = 60) -> str:
    """Whitespace-collapsed text, cut at a word boundary with an ellipsis."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit].rsplit(" ", 1)[0] + "…"
