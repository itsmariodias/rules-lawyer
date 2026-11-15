"""A fake chat model, and a chat service answered by it, for the test suites.

The model calls the real ``search_srd`` and cites the first result, so everything
but the model's wording is live.  ``tests.e2e_app`` serves the API with it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from functools import cached_property
from typing import Any
from uuid import uuid4

from fastapi import Request
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from rules_lawyer.chat.retrieval.search import CITATION
from rules_lawyer.chat.service import ChatService

# Fixed, made-up usage per call, so the usage event is exercised.
USAGE = {"input_tokens": 1200, "output_tokens": 30, "total_tokens": 1230}


class FakeChatModel(BaseChatModel):
    """Calls ``search_srd`` with the question, then cites the first result.

    Asked for a title, it calls the search too, so its reply has no text and
    conversations stay untitled: the list shows the cut question.
    """

    @property
    def _llm_type(self) -> str:
        return "fake-srd"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> FakeChatModel:
        """Ignore ``tools``; the script only ever calls ``search_srd``.

        Args:
            tools: The agent's tools.
            **kwargs: Binding options, ignored.

        Returns:
            This model, unchanged.
        """
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



class FakeChatService(ChatService):
    """A ``ChatService`` answered by ``FakeChatModel``, which needs no key."""

    @cached_property
    def model(self) -> BaseChatModel:
        """The fake model."""
        return FakeChatModel()


def fake_chat_service(request: Request) -> ChatService:
    """``routes.chat_service`` answered by the fake, for ``dependency_overrides``.

    Args:
        request: The request, whose app holds the checkpointer and store.

    Returns:
        The fake service over the app's storage.
    """
    return FakeChatService(request.app.state.checkpointer, request.app.state.store)
