"""
Stage 3 over HTTP: the chat stream, its threads, and what a citation opens.

The routes hold no state.  The checkpointer and the store are opened once by
the app's lifespan and reached through ``request.app.state`` as dependencies,
so a conversation is addressed only by the thread id the browser holds.
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

from . import agent as chat_agent
from . import neighbourhood as graph_view
from . import service, titles
from .source import excerpt

router = APIRouter(tags=["chat"])


def conversations(request: Request) -> BaseCheckpointSaver:
    """The process-wide checkpointer, opened by the app's lifespan."""
    return request.app.state.checkpointer


def flags(request: Request) -> BaseStore:
    """The process-wide store of what is true about a conversation."""
    return request.app.state.store


Conversations = Annotated[BaseCheckpointSaver, Depends(conversations)]
Flags = Annotated[BaseStore, Depends(flags)]


class PinRequest(BaseModel):
    pinned: bool


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    # Absent on the first message of a conversation; the response stream
    # reports the id that was minted so the browser can keep using it.
    thread_id: str | None = None


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/chat")
async def chat(request: ChatRequest, checkpointer: Conversations,
               store: Flags) -> StreamingResponse:
    """
    One turn, streamed as server-sent events.

    Events are ``token`` (a fragment of the answer), ``tool_start`` and
    ``tool_end`` (the searches the agent ran, so the UI can show its
    working), ``usage`` (the tokens every model call in the turn read and
    wrote, summed), ``citations`` (resolved once the answer is complete),
    ``error`` (the model could not answer, and nothing answers in its
    place), and finally ``done``.

    A missing key is the one failure knowable before the response is
    committed, so it is an HTTP error rather than an event buried inside a
    stream that had already announced itself as a turn.  Everything that can
    only fail mid-call — a rejected key, a spent quota, a stall — arrives as
    ``error``.

    The opening turn of a conversation also has it titled, by a call that
    runs beside the turn rather than before it, so the first token waits for
    nothing. It is stored before the stream ends, which is when the browser
    refreshes its thread list.
    """
    try:
        chat_agent.build_agent(checkpointer)
    except chat_agent.NoApiKey as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    thread_id = request.thread_id or uuid4().hex
    # Whether this is the opening turn is asked of the checkpointer rather
    # than read off a missing id, since a client may mint its own.
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
            # A reader who stops the turn has left; nothing is waiting on it.
            if titling is not None:
                titling.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # Without this a reverse proxy will happily buffer the whole answer
        # and deliver it in one piece, which defeats the point.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/threads/{thread_id}/retry")
async def retry_turn(thread_id: str,
                     checkpointer: Conversations) -> StreamingResponse:
    """
    Ask the last question again, in place of the answer it got.

    The same events ``/chat`` sends, and the same rule about which failures
    are HTTP: the key and the rewind are both knowable before the response is
    committed, so a missing key is a 503 and a thread with nothing in it is a
    404 rather than an event inside a stream that has already announced
    itself as a turn.

    The browser sends no message.  What was asked is in the checkpoint, and
    reading it there is what keeps the retry a rewind rather than a second
    question that happens to match.
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
    Pin or unpin one conversation, which decides where it sits in the list.

    Checked against the checkpointer first: a pin on a thread that does not
    exist is a row nothing would ever read.
    """
    if await checkpointer.aget_tuple(
            {"configurable": {"thread_id": thread_id}}) is None:
        raise HTTPException(status_code=404, detail=f"no thread {thread_id!r}")
    await service.set_pinned(store, thread_id, request.pinned)


@router.get("/chat/threads/{thread_id}")
async def chat_thread(thread_id: str, checkpointer: Conversations) -> dict:
    """One conversation's turns, for reopening it in the UI."""
    messages = await service.history(thread_id, checkpointer)
    if not messages:
        raise HTTPException(status_code=404, detail=f"no thread {thread_id!r}")
    return {"thread_id": thread_id, "messages": messages}


@router.get("/chat/threads/{thread_id}/lookups/{call_id}")
async def chat_lookup(thread_id: str, call_id: str,
                      checkpointer: Conversations) -> dict:
    """
    What one lookup in a conversation returned.

    Its own request rather than part of the conversation: the results are
    large, most are never opened, and the trace's counts are enough until
    someone asks to see one.
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
    Delete one conversation: its turns, its tool calls and its pin.

    404 when there was nothing under that id, so the UI can tell a delete
    from a no-op.
    """
    if not await service.forget(thread_id, checkpointer, store):
        raise HTTPException(status_code=404, detail=f"no thread {thread_id!r}")


@router.get("/source/{section_id}")
async def source(section_id: str, context: int = 0) -> dict:
    """
    The SRD text behind a citation, sliced out of ``srd_hierarchy.md`` by the
    character offsets the graph carries, plus the rectangles those lines
    occupy on the page.

    ``context`` widens the slice; ``highlight`` says where the cited section
    sits within it, and ``boxes`` always marks the citation itself.
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
    The graph around one node: the nodes ``depth`` hops from it, and the
    edges between them.

    Exactly one of ``section`` (a dotted section id, as ``/source`` takes)
    and ``node`` (a ``uid`` this endpoint returned earlier).  Both exist
    because a drawn node may be a creature ability or a damage type, which
    has no section id to be named by.

    ``fan`` and ``limit`` bound the answer; whatever they cut is counted in
    ``truncated`` rather than dropped in silence.
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
