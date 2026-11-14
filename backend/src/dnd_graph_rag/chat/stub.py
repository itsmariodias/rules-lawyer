"""
A scripted chat model for the test suites, selected by ``CHAT_STUB``.

Never a fallback for a failing provider.  In the package rather than
``tests/`` because e2e runs a real uvicorn process configured by environment.
It calls the real ``search_srd`` and cites the first result, so everything
but the model's wording is live.
"""

from __future__ import annotations

import json
from typing import Any, Iterator, Sequence
from uuid import uuid4

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from dnd_graph_rag.chat.retrieval import CITATION

# Fixed, made-up usage per call, so the usage event is exercised.
USAGE = {"input_tokens": 1200, "output_tokens": 30, "total_tokens": 1230}


class ScriptedModel(BaseChatModel):
    """Calls ``search_srd`` with the question, then cites the first result."""

    @property
    def _llm_type(self) -> str:
        return "scripted-srd"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedModel":
        """Ignore ``tools``; the script only ever calls ``search_srd``."""
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
        """A tool call as one chunk; an answer as one chunk per word."""
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
            # Only on the last chunk: LangChain sums usage when merging chunks.
            last = index == len(words) - 1
            yield ChatGenerationChunk(message=AIMessageChunk(
                content=word + " ",
                usage_metadata=dict(USAGE) if last else None))


def _reply(messages: list[BaseMessage]) -> AIMessage:
    """A search call if no tool has answered yet, otherwise the answer."""
    results = [m for m in messages if isinstance(m, ToolMessage)]
    if not results:
        return AIMessage(content="", tool_calls=[{
            "name": "search_srd",
            "args": {"query": _question(messages)},
            "id": uuid4().hex,
        }])
    return AIMessage(content=_answer(str(results[-1].content)))


def _question(messages: list[BaseMessage]) -> str:
    """The text of the last human message."""
    for message in reversed(messages):
        if getattr(message, "type", None) == "human":
            return str(message.content)
    return ""


def _answer(result: str) -> str:
    """A sentence citing the first section id in a search result."""
    found = CITATION.search(result)
    if found is None:
        return "The SRD search found nothing for that."
    return (f"The SRD covers this in section [{found.group(1)}], which is "
            "the passage the search returned first.")
