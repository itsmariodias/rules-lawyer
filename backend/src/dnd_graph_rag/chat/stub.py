"""
A scripted chat model, so the stack can be driven without a provider.

This is a **test seam**, not a fallback.  It is off unless ``CHAT_STUB`` is
set, and nothing ever turns it on in response to a failure: a missing key, a
rejected key or a spent quota fails the turn, as they must.  What it exists
for is the suite — ``tests/chat/test_routes.py`` and the whole of ``e2e``
need a deterministic answer, and paying a provider per assertion would make
them slow, flaky and rationed.

It lives in the package rather than in ``tests/`` because ``e2e`` drives a
real uvicorn subprocess, which can only be steered by the environment.

It is scripted rather than canned: it calls the real ``search_srd`` against
the real graph and cites what comes back, so the agent loop, the tools, the
streaming, the checkpointing and the citation resolution are all the live
ones.  Only the sentences are fake.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator, Sequence
from uuid import uuid4

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (AIMessage, AIMessageChunk, BaseMessage,
                                     ToolMessage)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

# The form the system prompt asks a real answer for, and the form the tools
# lead every result with, so one is read out of the other.
CITATION = re.compile(r"\[(\d+(?:\.\d+)+)\]")

# What every scripted call claims to have cost.  Made up, like the
# sentences: it is here so the usage a turn reports is exercised end to end,
# not to say anything about what a real call costs.
USAGE = {"input_tokens": 1200, "output_tokens": 30, "total_tokens": 1230}


class ScriptedModel(BaseChatModel):
    """
    Two steps: search for the question, then cite the first thing found.

    That is the shape of every real turn — a tool call, a tool result, an
    answer carrying citations — which is what makes it worth asserting
    against.
    """

    @property
    def _llm_type(self) -> str:
        return "scripted-srd"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedModel":
        """The script knows which tool it calls, so the list is not needed."""
        return self

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: CallbackManagerForLLMRun | None = None,
                  **kwargs: Any) -> ChatResult:
        reply = _reply(messages)
        reply.usage_metadata = dict(USAGE)
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def _stream(self, messages: list[BaseMessage], stop: list[str] | None = None,
                run_manager: CallbackManagerForLLMRun | None = None,
                **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        """
        Streamed, because the UI's whole shape is that an answer arrives.

        A tool call is one chunk — nothing downstream draws it until its
        arguments are complete anyway — and prose is split into words.
        """
        reply = _reply(messages)
        if reply.tool_calls:
            call = reply.tool_calls[0]
            yield ChatGenerationChunk(message=AIMessageChunk(
                content="",
                tool_call_chunks=[{
                    "name": call["name"],
                    "args": json.dumps(call["args"]),
                    "id": call["id"],
                    "index": 0,
                }],
                usage_metadata=dict(USAGE),
            ))
            return
        words = str(reply.content).split(" ")
        for index, word in enumerate(words):
            # Once per call, on the last chunk: merged chunks sum their counts.
            last = index == len(words) - 1
            yield ChatGenerationChunk(message=AIMessageChunk(
                content=word + " ",
                usage_metadata=dict(USAGE) if last else None))


def _reply(messages: list[BaseMessage]) -> AIMessage:
    """The next scripted message, decided by what is already in the thread."""
    results = [m for m in messages if isinstance(m, ToolMessage)]
    if not results:
        return AIMessage(content="", tool_calls=[{
            "name": "search_srd",
            "args": {"query": _question(messages)},
            "id": uuid4().hex,
        }])
    return AIMessage(content=_answer(str(results[-1].content)))


def _question(messages: list[BaseMessage]) -> str:
    """The message being answered: the last one the reader sent."""
    for message in reversed(messages):
        if getattr(message, "type", None) == "human":
            return str(message.content)
    return ""


def _answer(result: str) -> str:
    """
    A sentence citing the first section the search returned.

    Only the first: a citation is what the rest of the application is built
    on, and one that resolves proves the chain end to end.
    """
    found = CITATION.search(result)
    if found is None:
        return "The SRD search found nothing for that."
    return (f"The SRD covers this in section [{found.group(1)}], which is "
            "the passage the search returned first.")
