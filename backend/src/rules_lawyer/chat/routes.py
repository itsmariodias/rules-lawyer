"""
Stage 3 over HTTP: the chat stream, threads, citation sources and the graph view.

The checkpointer and store come from ``request.app.state`` (see
``api.lifespan``).
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from rules_lawyer.chat import agent as chat_agent
from rules_lawyer.chat import neighbourhood as graph_view
from rules_lawyer.chat import service, titles
from rules_lawyer.chat.source import excerpt

router = APIRouter(tags=["chat"])


def conversations(request: Request) -> BaseCheckpointSaver:
    """The process-wide checkpointer, opened by the app's lifespan."""
    return request.app.state.checkpointer


def flags(request: Request) -> BaseStore:
    """The process-wide pin and title store, opened by the app's lifespan."""
    return request.app.state.store


Conversations = Annotated[BaseCheckpointSaver, Depends(conversations)]
Flags = Annotated[BaseStore, Depends(flags)]


class PinRequest(BaseModel):
    pinned: bool


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    # Omitted to start a thread; the ``start`` event carries the minted id.
    thread_id: str | None = None


def _sse(event: dict) -> str:
    """One server-sent event frame."""
    return f"data: {json.dumps(event)}\n\n"


@router.post("/chat")
async def chat(request: ChatRequest, checkpointer: Conversations,
               store: Flags) -> StreamingResponse:
    """
    One turn, streamed as server-sent events.

    Events: ``start``, ``token``, ``tool_start``, ``tool_end``, ``usage``,
    ``citations``, ``error`` and ``done``.  Failures after the stream starts
    arrive as ``error``.  On a thread's first turn a title is generated
    concurrently and stored before the stream ends.

    Raises:
        HTTPException: 503 if no API key is configured.
    """
    try:
        chat_agent.build_agent(checkpointer)
    except chat_agent.NoApiKey as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    thread_id = request.thread_id or uuid4().hex
    # Checked in storage, not by a missing id: a client may mint its own.
    opening = await checkpointer.aget_tuple(
        {"configurable": {"thread_id": thread_id}}) is None

    async def events() -> AsyncIterator[str]:
        titling = (asyncio.create_task(titles.summarise(request.message))
                   if opening else None)
        try:
            yield _sse({"type": "start", "thread_id": thread_id})
            async for event in service.stream_turn(
                    request.message, thread_id, checkpointer):
                yield _sse(event)
            if titling is not None and (title := await titling):
                await titles.remember(store, thread_id, title)
        finally:
            # The client disconnected; nothing will read the title.
            if titling is not None:
                titling.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # Stops nginx-style proxies buffering the stream.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/threads/{thread_id}/retry")
async def retry_turn(thread_id: str,
                     checkpointer: Conversations) -> StreamingResponse:
    """
    Re-ask the last question, replacing its answer (see ``service.rewind``).

    Streams the same events as ``/chat``.  The question is read from the
    checkpoint, not sent by the client.

    Raises:
        HTTPException: 503 if no API key is configured; 404 if the thread
            has no question.
    """
    try:
        chat_agent.build_agent(checkpointer)
    except chat_agent.NoApiKey as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    rewound = await service.rewind(thread_id, checkpointer)
    if rewound is None:
        raise HTTPException(status_code=404, detail=f"no thread {thread_id!r}")
    message, checkpoint_id = rewound

    async def events() -> AsyncIterator[str]:
        yield _sse({"type": "start", "thread_id": thread_id})
        async for event in service.stream_turn(
                message, thread_id, checkpointer, checkpoint_id):
            yield _sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chat/threads")
async def chat_threads(checkpointer: Conversations, store: Flags,
                       limit: int = 50) -> dict:
    """Stored conversations, pinned first and newest first within that."""
    return {"threads": await service.threads(checkpointer, store, limit)}


@router.put("/chat/threads/{thread_id}/pin", status_code=204)
async def pin_thread(thread_id: str, request: PinRequest,
                     checkpointer: Conversations, store: Flags) -> None:
    """
    Pin or unpin one conversation.

    Raises:
        HTTPException: 404 if the thread does not exist.
    """
    if await checkpointer.aget_tuple(
            {"configurable": {"thread_id": thread_id}}) is None:
        raise HTTPException(status_code=404, detail=f"no thread {thread_id!r}")
    await service.set_pinned(store, thread_id, request.pinned)


@router.get("/chat/threads/{thread_id}")
async def chat_thread(thread_id: str, checkpointer: Conversations) -> dict:
    """
    One conversation's turns.

    Raises:
        HTTPException: 404 if the thread does not exist.
    """
    messages = await service.history(thread_id, checkpointer)
    if not messages:
        raise HTTPException(status_code=404, detail=f"no thread {thread_id!r}")
    return {"thread_id": thread_id, "messages": messages}


@router.get("/chat/threads/{thread_id}/lookups/{call_id}")
async def chat_lookup(thread_id: str, call_id: str,
                      checkpointer: Conversations) -> dict:
    """
    One tool call's stored result, fetched on demand because results are large.

    Raises:
        HTTPException: 404 if the thread has no such call.
    """
    found = await service.lookup(thread_id, call_id, checkpointer)
    if found is None:
        raise HTTPException(status_code=404,
                            detail=f"no lookup {call_id!r} in {thread_id!r}")
    return found


@router.delete("/chat/threads/{thread_id}", status_code=204)
async def forget_thread(thread_id: str, checkpointer: Conversations,
                        store: Flags) -> None:
    """
    Delete one conversation, its pin and its title.

    Raises:
        HTTPException: 404 if the thread does not exist.
    """
    if not await service.forget(thread_id, checkpointer, store):
        raise HTTPException(status_code=404, detail=f"no thread {thread_id!r}")


@router.get("/source/{section_id}")
async def source(section_id: str, context: int = 0) -> dict:
    """
    A cited section's text and page boxes; see ``source.excerpt``.

    Raises:
        HTTPException: 503 if the markdown is missing; 404 if the section is.
    """
    try:
        found = await run_in_threadpool(excerpt, section_id, context)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if found is None:
        raise HTTPException(status_code=404, detail=f"no section {section_id!r}")
    return found


@router.get("/neighbourhood")
async def neighbourhood(section: str | None = None, node: str | None = None,
                        depth: int = 1,
                        fan: int = graph_view.FAN,
                        limit: int = graph_view.LIMIT) -> dict:
    """
    The bounded graph around one node; see ``neighbourhood.neighbourhood``.

    Pass exactly one of ``section`` (a dotted id) or ``node`` (a ``uid`` from
    an earlier response; derived nodes have no section id).

    Raises:
        HTTPException: 400 unless exactly one is given; 404 if not found.
    """
    if (section is None) == (node is None):
        raise HTTPException(
            status_code=400,
            detail="pass exactly one of section= or node=")

    found = await run_in_threadpool(
        graph_view.neighbourhood, section_id=section, uid=node,
        depth=depth, fan=max(1, fan), limit=max(1, limit))
    if found is None:
        raise HTTPException(status_code=404,
                            detail=f"no node for {section or node!r}")
    return found
