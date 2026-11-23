"""The chat service: asking, retrying, and the stored conversations.

Threads live in the checkpointer, pins and titles in the store.  Only
asking and retrying build the model, so stored conversations are read,
listed, pinned and deleted without an API key.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date
from functools import cached_property
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from neo4j.exceptions import ServiceUnavailable

from rules_lawyer.chat import threads
from rules_lawyer.chat.agent import titles
from rules_lawyer.chat.agent.model import model as configured_model
from rules_lawyer.chat.export import Export, ExportFormat, render
from rules_lawyer.chat.turn import stream_turn, thread_config

PINS = ("threads", "pinned")

# Checkpoints scanned per thread listed.  One turn writes one per step, and
# a turn of 20 lookups writes over 40, so older threads fall outside the
# scan; pinned threads are fetched by id instead.
CHECKPOINTS_PER_THREAD = 40


class ChatService:
    """Conversations over one checkpointer and store.

    Args:
        checkpointer: Conversation storage.
        store: Pins and titles.
    """

    def __init__(self, checkpointer: BaseCheckpointSaver, store: BaseStore):
        self.checkpointer = checkpointer
        self.store = store

    @cached_property
    def model(self) -> BaseChatModel:
        """The chat model that answers and titles, built on first use.

        Raises:
            ModelUnavailable: No model can be built (no key, model or
                package).
        """
        return configured_model()

    async def ask(self, message: str,
                  thread_id: str | None = None) -> AsyncIterator[dict]:
        """One turn, as events.  On a thread's first turn, title it too.

        The model is built before the stream is returned, so a missing key
        fails the request rather than the stream.  The title is asked for
        beside the turn, so the first token waits for nothing, and is stored
        and sent as soon as the model gives it, before ``done`` at the latest.

        Args:
            message: The user's question.
            thread_id: The thread to add it to; omitted to start one.

        Returns:
            ``{"type": "start", "thread_id"}``, then ``stream_turn``'s events,
            with ``{"type": "title", "thread_id", "title"}`` among them on a
            thread's first turn: the model's title, or the cut question if
            it gave none.

        Raises:
            ModelUnavailable: No model can be built (no key, model or
                package).
        """
        model = self.model
        thread_id = thread_id or uuid4().hex
        # Checked in storage, not by a missing id: a client may mint its own.
        opening = await self.checkpointer.aget_tuple(
            thread_config(thread_id)) is None

        # Both tasks feed one queue, so the title is sent between whichever
        # events it falls; None marks the end of the turn.
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        async def title() -> None:
            named = await titles.summarise(message, model)
            if named:
                await titles.remember(self.store, thread_id, named)
            # Unstored without a title: the list falls back to the same cut.
            queue.put_nowait({"type": "title", "thread_id": thread_id,
                              "title": named or threads.short_title(message)})

        async def answer(titling: asyncio.Task | None) -> None:
            try:
                async for event in stream_turn(
                        message, thread_id, self.checkpointer, model):
                    if event["type"] == "done" and titling is not None:
                        await titling
                    queue.put_nowait(event)
            finally:
                queue.put_nowait(None)

        async def events() -> AsyncIterator[dict]:
            titling = asyncio.create_task(title()) if opening else None
            answering = asyncio.create_task(answer(titling))
            try:
                yield {"type": "start", "thread_id": thread_id}
                while (event := await queue.get()) is not None:
                    yield event
                await answering
            finally:
                # The client disconnected; nothing will read the rest.
                answering.cancel()
                if titling is not None:
                    titling.cancel()

        return events()

    async def retry(self, thread_id: str) -> AsyncIterator[dict] | None:
        """Re-ask a thread's last question, replacing its answer.

        The checkpointer cannot delete one checkpoint, so the retry branches
        from the newest checkpoint without the last question; later ones stay
        on disk, unreachable.  The graph checkpoints before the input, so the
        first turn also has a state to branch from.

        Args:
            thread_id: The conversation.

        Returns:
            The turn's events, as ``ask`` returns them; None if the thread
            has no question.

        Raises:
            ModelUnavailable: No model can be built; checked before the thread.
        """
        model = self.model
        asked = threads.last_question(await self._messages(thread_id))
        if asked is None:
            return None
        message, message_id = asked

        checkpoint_id = None
        # Newest first.
        async for item in self.checkpointer.alist(thread_config(thread_id)):
            stored = threads.checkpointed(item.checkpoint)
            if not any(getattr(m, "id", None) == message_id for m in stored):
                checkpoint_id = item.config["configurable"]["checkpoint_id"]
                break
        else:
            # Nothing predates the question: restart the thread under its id.
            await self.checkpointer.adelete_thread(thread_id)

        async def events() -> AsyncIterator[dict]:
            yield {"type": "start", "thread_id": thread_id}
            async for event in stream_turn(message, thread_id, self.checkpointer,
                                           model, checkpoint_id):
                yield event

        return events()

    async def history(self, thread_id: str) -> list[dict]:
        """One thread's turns, with tool traces, timestamps and usage.

        Args:
            thread_id: The conversation.

        Returns:
            See ``threads.turns_of``; empty for an unknown thread.  With the
            graph unreachable, the turns come back without citations or
            lookup headings, which only the graph can resolve.
        """
        messages = await self._messages(thread_id)
        when = await self._written_at(thread_id)

        def read() -> list[dict]:
            try:
                return threads.name_missing_subjects(
                    threads.turns_of(messages, when))
            except ServiceUnavailable:
                return threads.turns_of(messages, when, cite=lambda text: [])

        # Both resolve section ids with synchronous graph queries.
        return await asyncio.to_thread(read)

    async def export(self, thread_id: str, kind: ExportFormat) -> Export | None:
        """One thread as a file to download.

        Args:
            thread_id: The conversation.
            kind: The file type.

        Returns:
            The file, titled as the thread list titles it; None for an
            unknown thread.  With the graph unreachable the answers have no
            sources, as in ``history``.
        """
        turns = await self.history(thread_id)
        if not turns:
            return None
        stored = await self.store.aget(titles.TITLES, thread_id)
        title = (stored.value["title"] if stored
                 else threads.short_title(turns[0]["content"]))
        # Laying out a PDF takes CPU time that would stall every open stream.
        return await asyncio.to_thread(render, title, turns, kind, date.today())

    async def lookup(self, thread_id: str, call_id: str) -> dict | None:
        """One tool call's stored result, read from the thread's latest state.

        Each result is stored as its tool finishes, so this also works while
        the turn is still streaming.

        Args:
            thread_id: The conversation the call was made in.
            call_id: The tool call's id.

        Returns:
            See ``threads.find_result``.
        """
        return threads.find_result(await self._messages(thread_id), call_id)

    async def list_threads(self, limit: int = 50) -> list[dict]:
        """Stored threads, pinned first, then most recently updated.

        Args:
            limit: Maximum unpinned threads returned.  Every pinned thread is
                returned, however old.

        Returns:
            ``{"thread_id", "title", "updated_at", "messages", "pinned"}`` per
            thread.  The title falls back to the cut opening question.
        """
        pins = await self._pinned()
        named = await titles.titled(self.store)
        # Thread id -> its newest checkpoint; ``alist`` yields newest first.
        newest: dict[str, dict] = {}
        async for item in self.checkpointer.alist(
                None, limit=limit * CHECKPOINTS_PER_THREAD):
            newest.setdefault(item.config["configurable"]["thread_id"],
                              item.checkpoint)
        for thread_id in pins - newest.keys():
            saved = await self.checkpointer.aget_tuple(thread_config(thread_id))
            if saved is not None:
                newest[thread_id] = saved.checkpoint

        listed: list[dict] = []
        for thread_id, checkpoint in newest.items():
            messages = threads.checkpointed(checkpoint)
            questions = [m for m in messages if isinstance(m, HumanMessage)]
            if not questions:
                continue  # only the pre-input checkpoint so far
            listed.append({
                "thread_id": thread_id,
                "title": named.get(thread_id) or threads.short_title(questions[0].text),
                "updated_at": checkpoint.get("ts"),
                "messages": len(questions),
                "pinned": thread_id in pins,
            })
        listed.sort(key=lambda t: t["updated_at"] or "", reverse=True)
        pinned_first = [t for t in listed if t["pinned"]]
        return pinned_first + [t for t in listed if not t["pinned"]][:limit]

    async def set_pinned(self, thread_id: str, pin: bool) -> bool:
        """Pin a thread, or unpin it by deleting its row.

        Args:
            thread_id: The conversation.
            pin: True to pin, False to unpin.

        Returns:
            False if the thread does not exist.
        """
        if await self.checkpointer.aget_tuple(thread_config(thread_id)) is None:
            return False
        if pin:
            await self.store.aput(PINS, thread_id, {"pinned": True})
        else:
            await self.store.adelete(PINS, thread_id)
        return True

    async def forget(self, thread_id: str) -> bool:
        """Delete a thread's checkpoints, pin and title.

        Args:
            thread_id: The conversation.

        Returns:
            False if the thread had no checkpoints.
        """
        if await self.checkpointer.aget_tuple(thread_config(thread_id)) is None:
            return False
        await self.checkpointer.adelete_thread(thread_id)
        await self.store.adelete(PINS, thread_id)
        await titles.forget(self.store, thread_id)
        return True

    async def _messages(self, thread_id: str) -> list:
        """A thread's messages, read from storage without building the agent.

        Tool results already written by a step still running are included,
        as ``aget_state`` includes them.
        """
        saved = await self.checkpointer.aget_tuple(thread_config(thread_id))
        if saved is None:
            return []
        messages = list(threads.checkpointed(saved.checkpoint))
        stored = {message.id for message in messages if message.id}
        for _, channel, value in saved.pending_writes or []:
            if channel != "messages":
                continue
            for message in value if isinstance(value, list) else [value]:
                if not message.id or message.id not in stored:
                    messages.append(message)
        return messages

    async def _written_at(self, thread_id: str) -> dict[str, str]:
        """Message id to the timestamp of the earliest checkpoint containing it.

        ``alist`` yields newest first, so the last write per id is the earliest.
        """
        when: dict[str, str] = {}
        async for item in self.checkpointer.alist(thread_config(thread_id)):
            stamp = item.checkpoint.get("ts")
            if not stamp:
                continue
            for message in threads.checkpointed(item.checkpoint):
                message_id = getattr(message, "id", None)
                if message_id:
                    when[message_id] = stamp
        return when

    async def _pinned(self) -> set[str]:
        """The pinned thread ids."""
        # ``asearch`` defaults to ten, which silently unpinned the eleventh.
        return {item.key for item in
                await self.store.asearch(PINS, limit=titles.EVERY)}
