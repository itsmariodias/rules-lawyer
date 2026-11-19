"""Stored conversations as the UI shows them: turns, traces and results.

Nothing here touches storage: ``ChatService`` reads the checkpoints and
passes their messages in.
"""

from __future__ import annotations

from collections.abc import Callable

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from rules_lawyer.chat.retrieval import search
from rules_lawyer.chat.turn import resolve_citations, tool_outcome, usage_of


def _call_row(call: dict) -> dict:
    """One tool call, in the shape ``tool_start`` sends it live."""
    return {"id": call["id"], "name": call["name"],
            "args": call.get("args") or {},
            "done": False, "status": None, "summary": None,
            "subject": None}


def _close_row(row: dict, message: ToolMessage) -> None:
    """Mark a trace row done with its stored result's outcome."""
    row["done"] = True
    row.update(tool_outcome(message))


def turns_of(messages: list, when: dict[str, str] | None = None,
             cite: Callable[[str], list[dict]] = resolve_citations) -> list[dict]:
    """A stored conversation as UI turns.

    Tool calls attach to the assistant answer that follows them.  Calls from
    a turn that ended without an answer are discarded at the next question.

    Args:
        messages: The thread's messages, in order.
        when: Message id to ISO timestamp, from ``written_at``.
        cite: An answer's text to its citations.

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
                              "citations": cite(text),
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
                found = search.get_section(section_id)
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


def checkpointed(checkpoint: dict) -> list:
    """The messages stored in one checkpoint.

    Args:
        checkpoint: A checkpoint as the checkpointer returns it.

    Returns:
        Its messages; empty if it holds none.
    """
    return (checkpoint.get("channel_values") or {}).get("messages", [])


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


def short_title(text: str, limit: int = 60) -> str:
    """A question cut short enough to title its thread.

    Args:
        text: The thread's opening question.
        limit: Maximum characters.

    Returns:
        The text with whitespace collapsed, cut at a word boundary with an
        ellipsis.
    """
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit].rsplit(" ", 1)[0] + "…"
