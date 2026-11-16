"""One chat turn as a stream of typed events.

``stream_turn`` yields ``token``, ``tool_start``, ``tool_end``, ``usage``,
``citations``, ``error`` and ``done`` dicts; ``chat.routes`` encodes them as
SSE.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from rules_lawyer.chat.agent.build import build_agent
from rules_lawyer.chat.retrieval import search
from rules_lawyer.config import KEY_VARIABLES, Provider, get_settings


def thread_config(thread_id: str, checkpoint_id: str | None = None) -> dict:
    """LangGraph run config for a thread.

    Args:
        thread_id: The conversation.
        checkpoint_id: Branch from this checkpoint instead of the latest
            (used by retry).

    Returns:
        The config to run or read the thread with.
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
    for match in search.CITATION.findall(text):
        if match not in seen:
            seen.append(match)

    citations = []
    for section_id in seen:
        found = search.get_section(section_id)
        if found is not None:
            citations.append(found[0].as_citation())
    return citations


async def stream_turn(message: str, thread_id: str,
                      checkpointer: BaseCheckpointSaver,
                      model: BaseChatModel,
                      checkpoint_id: str | None = None) -> AsyncIterator[dict]:
    """Run one user message and yield events until the turn ends.

    Never raises: any failure becomes an ``error`` event, followed by
    ``usage`` (if any calls were made) and ``done``.

    Args:
        message: The user's message.
        thread_id: Conversation id; history comes from the checkpointer.
        checkpointer: Conversation storage.
        model: The chat model that answers.
        checkpoint_id: Branch from this checkpoint instead of the latest
            (see ``ChatService.retry``).

    Yields:
        Event dicts, ending with ``{"type": "done", "thread_id"}``.
    """
    config = thread_config(thread_id, checkpoint_id)
    answer: list[str] = []
    announced: set[str] = set()
    spoken: list[AIMessage] = []

    try:
        # Building the agent reads the graph schema, a synchronous query.
        agent = await asyncio.to_thread(build_agent, model, checkpointer)
        stream = agent.astream(
            {"messages": [HumanMessage(content=message)]},
            config=config,
            stream_mode=["messages", "updates"],
        )
        async for mode, payload in _until_silent(
                stream, get_settings().chat.timeout_seconds):
            if mode == "messages":
                chunk, _ = payload
                for event in _from_message_chunk(chunk, answer):
                    yield event
            elif mode == "updates":
                finished = _model_messages(payload)
                spoken.extend(finished)
                for event in _tool_starts(finished, announced):
                    yield event
                for event in _from_update(payload):
                    yield event
    except Exception as exc:  # noqa: BLE001 - never raises: a failure is the reply
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
        except TimeoutError as exc:
            raise TimeoutError(
                f"the model sent nothing for {seconds:g}s") from exc


# Unrecognised provider errors are JSON blobs (Gemini's invalid-key one is
# 600 characters), so they are cut to this.
ERROR_CHARS = 220

# Each provider as the reader knows it.
PROVIDER_NAMES = {Provider.GOOGLE: "Google", Provider.OPENAI: "OpenAI",
                  Provider.ANTHROPIC: "Anthropic", Provider.OLLAMA: "Ollama"}
# How each provider words a rejected key: Google, OpenAI, Anthropic, and the
# status code any of them may give alone.
REJECTED_KEY = ("API_KEY_INVALID", "API key not valid", "invalid_api_key",
                "Incorrect API key", "authentication_error", "Error code: 401")
# A spent quota or a rate limit: Google, OpenAI, Anthropic, then the status.
SPENT_QUOTA = ("RESOURCE_EXHAUSTED", "insufficient_quota", "rate_limit_error",
               "429")
# Ollama not running: from httpx when LangChain calls it, from the ollama
# client otherwise.
UNREACHABLE = ("Connection refused", "Failed to connect to Ollama")


def _explain(exc: Exception) -> str:
    """An exception as a short sentence for the reader.

    Missing key, rejected key, spent quota, an unreachable or unpulled
    Ollama model and silence get fixed messages naming the configured
    provider; anything else is truncated to ``ERROR_CHARS``.
    """
    text = f"{type(exc).__name__}: {exc}"
    chat = get_settings().chat
    provider = chat.provider
    variable = KEY_VARIABLES.get(provider, "The API key")
    missing = next((name for name in KEY_VARIABLES.values()
                    if f"{name} is not set" in text), None)
    if missing:
        return f"{missing} is not set. Add it to .env and restart the server."
    if any(sign in text for sign in REJECTED_KEY):
        return (f"{variable} was rejected by {PROVIDER_NAMES[provider]}. "
                "Check the key in .env and restart the server.")
    if any(sign in text for sign in SPENT_QUOTA):
        return (f"The {PROVIDER_NAMES[provider]} quota is spent or the rate "
                "limit was hit. Wait, or check the account's limits.")
    if provider is Provider.OLLAMA and any(sign in text
                                           for sign in UNREACHABLE):
        return (f"Ollama is not reachable at {chat.ollama_base_url}. Start it "
                "(`ollama serve`) or set OLLAMA_BASE_URL.")
    if provider is Provider.OLLAMA and "not found" in text:
        return (f"Ollama has no model {chat.model}. Run `ollama pull "
                f"{chat.model}`.")
    if isinstance(exc, TimeoutError):
        return (f"The model stopped responding ({exc}). Nothing arrived, so "
                "the turn was ended rather than left hanging.")
    if len(text) <= ERROR_CHARS:
        return text
    return text[:ERROR_CHARS].rsplit(" ", 1)[0] + "…"


def _from_message_chunk(chunk: Any, answer: list[str]) -> list[dict]:
    """A ``token`` event for a chunk's text, which is also appended to
    ``answer``.

    Tool calls are announced from the finished message instead
    (``_tool_starts``): most providers stream a call's arguments over several
    chunks, so the first chunk naming a call has none of them yet.
    """
    if not isinstance(chunk, AIMessageChunk):
        return []
    text = _text_of(chunk)
    if not text:
        return []
    answer.append(text)
    return [{"type": "token", "text": text}]


def _tool_starts(messages: list[AIMessage], announced: set[str]) -> list[dict]:
    """One ``tool_start`` per tool call in finished model messages.

    The model's message is finished before its tools run, so each start
    precedes its ``tool_end``; ``announced`` dedupes across updates.
    """
    events: list[dict] = []
    for message in messages:
        for call in message.tool_calls:
            call_id = call.get("id")
            if call_id and call_id not in announced:
                announced.add(call_id)
                events.append({"type": "tool_start", "id": call_id,
                               "name": call["name"],
                               "args": call.get("args") or {}})
    return events


def tool_outcome(message: ToolMessage) -> dict:
    """A tool result's outcome, live or stored.

    Args:
        message: The tool's result.

    Returns:
        ``{"status", "summary", "subject"}``, from its artifact; ``failed``
        if the tool raised.
    """
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
                    **tool_outcome(message),
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
