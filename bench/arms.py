"""The four ways of answering a question, each timed and metered.

``graph`` and ``graph-lite`` are the app's own turn (``chat.turn.stream_turn``:
its tools, prompt, lookup budget and citations) on two models.
``full-srd`` gives the configured model the whole rendered SRD instead of
tools; ``closed-book`` gives it nothing.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from results import BENCH_DIR

from rules_lawyer.chat.agent.model import ModelUnavailable
from rules_lawyer.chat.retrieval.search import cited_ids
from rules_lawyer.chat.turn import stream_turn, thread_config
from rules_lawyer.config import get_settings

# The newest Flash-Lite that chats: "gemini-3.8-flash-lite" exists only as a
# text-to-speech model.
LITE_MODEL = "gemini-3.5-flash-lite"
# Every answering model thinks at the same level, so the two graph arms differ
# only in the model. The app sets none: Flash-Lite then defaults to "minimal",
# and 3.8 Flash spent about 5,000 thinking tokens on one list question.
THINKING_LEVEL = "low"

AGENT_ARMS = ("graph", "graph-lite")
ARMS = ("graph", "graph-lite", "full-srd", "closed-book")

# A section's id as inserted after its heading's hashes: "### [11.2.114] Prone".
_INSERTED_ID = re.compile(r"^(#+ )\[[0-9.]+\] ", re.MULTILINE)


@dataclass
class Answer:
    """One arm's answer to one question, with what it cost and how long it took."""

    question: str
    arm: str
    model: str
    thinking: str = THINKING_LEVEL
    text: str = ""
    cited: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    # input includes cached; output includes reasoning (thinking) tokens.
    usage: dict = field(default_factory=dict)
    first_token_seconds: float | None = None
    wall_seconds: float = 0.0
    error: str | None = None


def model_name(arm: str) -> str:
    """The model an arm answers with.

    Args:
        arm: One of ``ARMS``.

    Returns:
        ``LITE_MODEL`` for ``graph-lite``, the configured chat model otherwise.
    """
    return LITE_MODEL if arm == "graph-lite" else get_settings().chat.model


def chat_model(name: str) -> BaseChatModel:
    """Build a chat model of the configured provider, thinking at ``THINKING_LEVEL``.

    Args:
        name: The model id.

    Returns:
        The model.

    Raises:
        ModelUnavailable: The provider's key is not set.
    """
    settings = get_settings().chat.model_copy(update={"model": name})
    variable = settings.missing_key()
    if variable:
        raise ModelUnavailable(f"{variable} is not set")
    # LangChain's Gemini field for the thinking level is ``reasoning_effort``.
    return settings.model_provider.chat(settings).model_copy(
        update={"reasoning_effort": THINKING_LEVEL})


def srd_with_ids() -> str:
    """The rendered SRD with each section's id after its heading's hashes.

    Ids are inserted at each section's ``char_start``, where its heading
    line begins, so the full-srd arm can cite what the graph arms cite.

    Returns:
        The markdown, every section heading reading ``## [id] Heading``.

    Raises:
        RuntimeError: A section does not start at a heading, or removing the
            ids does not give back the rendered markdown exactly.
    """
    settings = get_settings()
    markdown = settings.output_path.with_suffix(".md").read_text(encoding="utf-8")
    document = json.loads(settings.output_path.read_text(encoding="utf-8"))

    starts: dict[int, str] = {}
    stack = list(document["sections"])
    while stack:
        section = stack.pop()
        starts[section["source"]["char_start"]] = section["id"]
        stack.extend(section["subsections"])

    pieces = []
    previous = 0
    for start in sorted(starts):
        hashes = re.match(r"#+ ", markdown[start:start + 8])
        if hashes is None:
            raise RuntimeError(f"section {starts[start]} does not start at a heading")
        after_hashes = start + hashes.end()
        pieces.append(markdown[previous:after_hashes])
        pieces.append(f"[{starts[start]}] ")
        previous = after_hashes
    pieces.append(markdown[previous:])
    with_ids = "".join(pieces)

    if _INSERTED_ID.sub(r"\1", with_ids) != markdown:
        raise RuntimeError("removing the inserted ids does not restore the markdown")
    return with_ids


def system_prompt(arm: str, document: str | None = None) -> str:
    """The system prompt of an arm that has no tools.

    Args:
        arm: ``full-srd`` or ``closed-book``.
        document: The SRD (``srd_with_ids``), for ``full-srd``.

    Returns:
        The prompt file's text, followed by the document if one is given.
        The document comes before any question, so every question shares
        the same prefix and Gemini's implicit caching can reuse it.
    """
    prompt = (BENCH_DIR / "prompts" / f"{arm}.md").read_text(encoding="utf-8").rstrip("\n")
    if document is None:
        return prompt
    return f"{prompt}\n\n<srd>\n{document}\n</srd>"


def usage_of(messages: list) -> dict:
    """Token usage summed over model messages, with the cached share of the input.

    Args:
        messages: Any messages; only ``AIMessage.usage_metadata`` is read.

    Returns:
        ``{"input", "cached", "output", "reasoning", "calls"}``, reasoning being
        the thinking share of output; zeros if none reported.
    """
    counted = [message.usage_metadata for message in messages
               if isinstance(message, AIMessage) and message.usage_metadata]
    return {
        "input": sum(usage.get("input_tokens", 0) for usage in counted),
        "cached": sum((usage.get("input_token_details") or {}).get("cache_read", 0)
                      for usage in counted),
        "output": sum(usage.get("output_tokens", 0) for usage in counted),
        "reasoning": sum((usage.get("output_token_details") or {}).get("reasoning", 0)
                         for usage in counted),
        "calls": len(counted),
    }


async def answer_with_tools(question: dict, arm: str, model: BaseChatModel) -> Answer:
    """Answer as the app does: one turn on a fresh thread.

    Args:
        question: A question from ``questions.yaml``.
        arm: ``graph`` or ``graph-lite``.
        model: The model to answer with.

    Returns:
        The answer; a failed turn has ``error`` set.
    """
    result = Answer(question=question["id"], arm=arm, model=model_name(arm))
    checkpointer = InMemorySaver()
    thread_id = uuid4().hex
    text: list[str] = []
    calls: dict[str, dict] = {}

    started = time.perf_counter()
    async for event in stream_turn(question["question"], thread_id, checkpointer, model):
        if event["type"] == "token":
            if result.first_token_seconds is None:
                result.first_token_seconds = time.perf_counter() - started
            text.append(event["text"])
        elif event["type"] == "tool_start":
            calls[event["id"]] = {"name": event["name"], "args": event["args"]}
        elif event["type"] == "tool_end":
            calls.setdefault(event["id"], {"name": event["name"]})["status"] = event["status"]
        elif event["type"] == "error":
            result.error = event["message"]
    result.wall_seconds = time.perf_counter() - started

    stored = await checkpointer.aget_tuple(thread_config(thread_id))
    messages = stored.checkpoint["channel_values"].get("messages", []) if stored else []
    result.text = "".join(text)
    result.cited = cited_ids(result.text)
    result.tool_calls = list(calls.values())
    result.usage = usage_of(messages)
    return result


async def answer_without_tools(question: dict, arm: str, model: BaseChatModel,
                               system: str) -> Answer:
    """Answer in one streamed call, with the SRD in the prompt or without it.

    Args:
        question: A question from ``questions.yaml``.
        arm: ``full-srd`` or ``closed-book``.
        model: The model to answer with.
        system: The arm's system prompt (``system_prompt``).

    Returns:
        The answer; a failed call has ``error`` set.
    """
    result = Answer(question=question["id"], arm=arm, model=model_name(arm))
    messages = [SystemMessage(content=system), HumanMessage(content=question["question"])]
    reply = None

    started = time.perf_counter()
    try:
        async for chunk in model.astream(messages):
            if chunk.text and result.first_token_seconds is None:
                result.first_token_seconds = time.perf_counter() - started
            # Adding chunks joins their text and sums their usage.
            reply = chunk if reply is None else reply + chunk
    except Exception as exc:  # noqa: BLE001 - a failed call is a result to report
        result.error = f"{type(exc).__name__}: {exc}"[:500]
    result.wall_seconds = time.perf_counter() - started

    if reply is not None:
        result.text = reply.text
        result.cited = cited_ids(result.text)
        result.usage = usage_of([reply])
    return result
