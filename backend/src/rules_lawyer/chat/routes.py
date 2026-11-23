"""Stage 3 over HTTP: the chat stream, threads, citation sources and the graph view.

Chat routes reach conversations through a ``ChatService`` over the app's
checkpointer and store (see ``api.lifespan``), from ``chat_service``, which
tests replace through ``app.dependency_overrides``.  Only asking and retrying
build the model, so the other routes work without a key.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from rules_lawyer.chat.agent.model import ModelUnavailable
from rules_lawyer.chat.export import ExportFormat
from rules_lawyer.chat.retrieval import neighbourhood as graph_view
from rules_lawyer.chat.retrieval.source import excerpt
from rules_lawyer.chat.service import ChatService

router = APIRouter(tags=["chat"])


def chat_service(request: Request) -> ChatService:
    """The conversations, over the app's checkpointer and store.

    Args:
        request: The request, whose app holds the checkpointer and store.

    Returns:
        The service; it builds its model only when asked to answer.
    """
    return ChatService(request.app.state.checkpointer, request.app.state.store)


Chat = Annotated[ChatService, Depends(chat_service)]


@contextmanager
def _answerable() -> Iterator[None]:
    """Turn an unbuildable model into a 503, before any stream starts.

    Raises:
        HTTPException: 503 if the model cannot be built (no key, model or
            package).
    """
    try:
        yield
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class PinRequest(BaseModel):
    """Whether the thread should be pinned."""

    pinned: bool


class ChatRequest(BaseModel):
    """One question, in a new thread or an existing one."""

    message: str = Field(min_length=1)
    # Omitted to start a thread; the ``start`` event carries the minted id.
    thread_id: str | None = None


def _streamed(events: AsyncIterator[dict]) -> StreamingResponse:
    """Events as a server-sent event response."""
    async def frames() -> AsyncIterator[str]:
        async for event in events:
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        # Stops nginx-style proxies buffering the stream.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat")
async def chat(request: ChatRequest, service: Chat) -> StreamingResponse:
    """One turn, streamed as server-sent events.

    Events: ``start``, ``token``, ``tool_start``, ``tool_end``, ``usage``,
    ``citations``, ``error`` and ``done``.  Failures after the stream starts
    arrive as ``error``.  On a thread's first turn a title is generated
    concurrently and stored before the stream ends.

    Args:
        request: The question, and the thread to add it to if not a new one.
        service: Conversations.

    Returns:
        The event stream.

    Raises:
        HTTPException: 503 if the model cannot be built (no key, model or
            package).
    """
    with _answerable():
        events = await service.ask(request.message, request.thread_id)
    return _streamed(events)


@router.post("/chat/threads/{thread_id}/retry")
async def retry_turn(thread_id: str, service: Chat) -> StreamingResponse:
    """Re-ask the last question, replacing its answer (see ``ChatService.retry``).

    Streams the same events as ``/chat``.  The question is read from the
    checkpoint, not sent by the client.

    Args:
        thread_id: The thread whose last question is asked again.
        service: Conversations.

    Returns:
        The event stream.

    Raises:
        HTTPException: 503 if the model cannot be built (no key, model or
            package); 404 if the thread has no question.
    """
    with _answerable():
        events = await service.retry(thread_id)
    if events is None:
        raise HTTPException(status_code=404, detail=f"no thread {thread_id!r}")
    return _streamed(events)


@router.get("/chat/threads")
async def chat_threads(service: Chat, limit: int = 50) -> dict:
    """Stored conversations, pinned first and newest first within that.

    Args:
        service: Conversations.
        limit: Maximum unpinned threads; every pinned thread is listed.

    Returns:
        ``{"threads"}``, as ``ChatService.list_threads`` lists them.
    """
    return {"threads": await service.list_threads(limit)}


@router.put("/chat/threads/{thread_id}/pin", status_code=204)
async def pin_thread(thread_id: str, request: PinRequest, service: Chat) -> None:
    """Pin or unpin one conversation.

    Args:
        thread_id: The conversation.
        request: Whether to pin it.
        service: Conversations.

    Raises:
        HTTPException: 404 if the thread does not exist.
    """
    if not await service.set_pinned(thread_id, request.pinned):
        raise HTTPException(status_code=404, detail=f"no thread {thread_id!r}")


@router.get("/chat/threads/{thread_id}")
async def chat_thread(thread_id: str, service: Chat) -> dict:
    """One conversation's turns.

    Args:
        thread_id: The conversation.
        service: Conversations.

    Returns:
        ``{"thread_id", "messages"}``, the turns as ``ChatService.history``
        reads them.

    Raises:
        HTTPException: 404 if the thread does not exist.
    """
    messages = await service.history(thread_id)
    if not messages:
        raise HTTPException(status_code=404, detail=f"no thread {thread_id!r}")
    return {"thread_id": thread_id, "messages": messages}


@router.get("/chat/threads/{thread_id}/export")
async def export_thread(
        thread_id: str, service: Chat,
        kind: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.MARKDOWN,
) -> Response:
    """One conversation as a file to download: markdown, Word or PDF.

    Args:
        thread_id: The conversation.
        service: Conversations.
        kind: The file type, ``?format=markdown|docx|pdf``.

    Returns:
        The file, as an attachment named for the thread's title.

    Raises:
        HTTPException: 404 if the thread does not exist.
    """
    exported = await service.export(thread_id, kind)
    if exported is None:
        raise HTTPException(status_code=404, detail=f"no thread {thread_id!r}")
    return Response(
        exported.content, media_type=exported.media_type,
        headers={"Content-Disposition":
                 f'attachment; filename="{exported.file_name}"'})


@router.get("/chat/threads/{thread_id}/lookups/{call_id}")
async def chat_lookup(thread_id: str, call_id: str, service: Chat) -> dict:
    """One tool call's stored result, fetched on demand because results are large.

    Args:
        thread_id: The conversation the call was made in.
        call_id: The tool call's id, from its ``tool_start`` event.
        service: Conversations.

    Returns:
        The result, as ``threads.find_result`` returns it.

    Raises:
        HTTPException: 404 if the thread has no such call.
    """
    found = await service.lookup(thread_id, call_id)
    if found is None:
        raise HTTPException(status_code=404,
                            detail=f"no lookup {call_id!r} in {thread_id!r}")
    return found


@router.delete("/chat/threads/{thread_id}", status_code=204)
async def forget_thread(thread_id: str, service: Chat) -> None:
    """Delete one conversation, its pin and its title.

    Args:
        thread_id: The conversation.
        service: Conversations.

    Raises:
        HTTPException: 404 if the thread does not exist.
    """
    if not await service.forget(thread_id):
        raise HTTPException(status_code=404, detail=f"no thread {thread_id!r}")


@router.get("/source/{section_id}")
async def source(section_id: str, context: int = 0) -> dict:
    """A cited section's text and page boxes; see ``source.excerpt``.

    Args:
        section_id: The dotted section id.
        context: Characters of markdown to include on each side.

    Returns:
        The excerpt.

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
    """The bounded graph around one node; see ``neighbourhood.neighbourhood``.

    Pass at most one of ``section`` (a dotted id) or ``node`` (a ``uid`` from
    an earlier response; derived nodes have no section id).  With neither,
    the seed is the book, a node joined to the 16 root sections.

    Args:
        section: Seed by dotted section id.
        node: Seed by ``uid``.
        depth: Hops to walk.
        fan: Neighbours per relationship type and direction, at least 1.
        limit: Maximum nodes, at least 1.

    Returns:
        ``root``, ``nodes``, ``edges`` and ``truncated``.

    Raises:
        HTTPException: 400 if both are given; 404 if not found.
    """
    if section is not None and node is not None:
        raise HTTPException(
            status_code=400,
            detail="pass at most one of section= or node=")

    found = await run_in_threadpool(
        graph_view.neighbourhood, section_id=section, uid=node,
        depth=depth, fan=max(1, fan), limit=max(1, limit))
    if found is None:
        raise HTTPException(status_code=404,
                            detail=f"no node for {section or node!r}")
    return found
