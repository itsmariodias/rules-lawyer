"""
One turn of conversation, as a flat stream of typed events.

Nothing here knows about HTTP: ``chat.routes`` encodes these dicts as SSE and
these tests iterate them directly.  The module also owns what a thread *is* —
listing, reading back, pinning and deleting — which lives in the checkpointer
and its store.
"""

from __future__ import annotations

import asyncio

import pytest

from dnd_graph_rag.chat import service


async def answer(saver, thread_id: str, question: str = "Prone condition") -> None:
    """One stored conversation, answered by the scripted model."""
    async for _ in service.stream_turn(question, thread_id, saver):
        pass


def raising(exc: Exception):
    """A ``build_agent`` that fails, standing in for a model that will."""
    def build(_checkpointer):
        raise exc

    return build


async def collect(message, saver) -> list[dict]:
    return [event async for event in
            service.stream_turn(message, "test", saver)]


class TestCitation:
    """A citation as the prompt asks for it."""

    def test_given_a_mix_of_brackets_when_matched_then_only_dotted_ids_count(self):
        """Anchored on the digits, so prose brackets never match."""
        # Given an answer carrying both kinds of bracket
        text = "Prone [11.2.114] and see [below] and [3] and [4.8.2.3]."

        # When the citations are found
        found = service.CITATION.findall(text)

        # Then only the dotted ids are citations
        assert found == ["11.2.114", "4.8.2.3"]


class TestResolveCitations:
    """The ids the model wrote, turned into citations the UI can open."""

    def test_given_an_invented_id_when_resolved_then_it_is_dropped(self, graph):
        """
        Driven by the finished answer rather than by what was retrieved, so
        an id the model invented resolves to nothing rather than rendering as
        a dead chip.
        """
        # Given an answer citing one real id and one invented one, twice
        text = "Real [11.2.114], invented [99.99.99], and again [11.2.114]."

        # When the citations are resolved
        citations = service.resolve_citations(text)

        # Then only what resolves survives, once
        assert [c["section_id"] for c in citations] == ["11.2.114"]

    def test_given_no_citations_at_all_when_resolved_then_the_list_is_empty(
            self, graph):
        # Given an answer citing nothing
        # When the citations are resolved
        # Then nothing is invented for it
        assert service.resolve_citations("No ids here.") == []


class TestExplain:
    """A provider error as a sentence the reader can act on."""

    def test_given_a_missing_key_when_explained_then_the_fix_is_in_the_sentence(self):
        # Given the error a missing key raises
        # When it is explained
        explained = service._explain(RuntimeError("GOOGLE_API_KEY is not set"))

        # Then it says where to put one
        assert "GOOGLE_API_KEY is not set" in explained
        assert ".env" in explained

    def test_given_a_rejected_key_when_explained_then_it_is_not_the_providers_json(self):
        """The invalid-key error is 600 characters carrying it twice."""
        # Given Google's own rejection
        error = RuntimeError("400 INVALID_ARGUMENT {'reason': 'API_KEY_INVALID'}")

        # When it is explained
        # Then the reader gets a sentence rather than a payload
        assert "GOOGLE_API_KEY was rejected" in service._explain(error)

    def test_given_a_spent_quota_when_explained_then_it_is_named_as_one(self):
        # Given the error a spent free tier raises
        # When it is explained
        explained = service._explain(RuntimeError("429 RESOURCE_EXHAUSTED: quota"))

        # Then the reader is told the model, not the answer, is the problem
        assert "quota" in explained.lower()

    def test_given_a_stall_when_explained_then_it_says_nothing_arrived(self):
        # Given a timeout
        # When it is explained
        explained = service._explain(TimeoutError("the model sent nothing for 60s"))

        # Then it says why the turn was ended rather than left hanging
        assert "stopped responding" in explained

    def test_given_an_error_nobody_anticipated_when_explained_then_it_stays_readable(self):
        """The error is now the answer, so it has to be readable."""
        # Given an enormous unrecognised error
        # When it is explained
        explained = service._explain(RuntimeError("boom " * 200))

        # Then it is capped at a length someone will still read
        assert len(explained) <= service.ERROR_CHARS + 1
        assert explained.endswith("…")

    def test_given_a_short_error_when_explained_then_it_is_passed_through_whole(self):
        # Given a short unrecognised error
        # When it is explained
        explained = service._explain(ValueError("something odd"))

        # Then nothing is cut from it
        assert explained == "ValueError: something odd"


class TestUntilSilent:
    """The agent's own stream, failed after a period of silence."""

    @pytest.mark.asyncio
    async def test_given_a_stalled_stream_when_run_then_the_turn_fails(self):
        """
        A stalled call never yields and never raises, so without this the
        turn hangs with no answer, no error and no offer.
        """
        # Given a stream that says nothing at all
        async def never_speaks():
            await asyncio.sleep(30)
            yield ("messages", None)

        # When it is run under a short silence limit
        # Then it fails rather than hanging
        with pytest.raises(TimeoutError, match="sent nothing"):
            async for _ in service._until_silent(never_speaks(), 0.05):
                pass

    @pytest.mark.asyncio
    async def test_given_a_slow_but_steady_stream_when_run_then_it_is_never_cut_off(self):
        """The limit is on silence, not on how long an answer may take."""
        # Given a stream slower overall than the limit but never silent for it
        async def slow_but_steady():
            for index in range(4):
                await asyncio.sleep(0.02)
                yield ("messages", index)

        # When it is run
        seen = [item async for item in
                service._until_silent(slow_but_steady(), 0.05)]

        # Then every event arrived
        assert [payload for _, payload in seen] == [0, 1, 2, 3]

    @pytest.mark.asyncio
    async def test_given_a_stream_that_ends_when_run_then_it_ends_cleanly(self):
        # Given a stream that finishes
        async def finishes():
            yield ("messages", 1)

        # When it is run
        seen = [item async for item in service._until_silent(finishes(), 1)]

        # Then exhaustion is not a timeout
        assert seen == [("messages", 1)]


class TestStreamTurn:
    """One user message, run until the answer is complete."""

    @pytest.mark.asyncio
    async def test_given_a_failed_model_when_run_then_the_error_is_the_answer(
            self, graph, saver, monkeypatch):
        """
        The model is required, so nothing stands in for it: a spent quota is
        a broken model, and saying so is the honest reply.
        """
        # Given a model that fails on the first call
        monkeypatch.setattr(service, "build_agent",
                            raising(RuntimeError("429 RESOURCE_EXHAUSTED")))

        # When the turn runs
        events = await collect("Prone condition", saver)

        # Then the failure is the whole of what is said
        error = next(e for e in events if e["type"] == "error")
        assert "quota" in error["message"].lower()
        assert [e["type"] for e in events] == ["error", "done"]

    @pytest.mark.asyncio
    async def test_given_a_failed_model_when_run_then_nothing_is_offered(
            self, graph, saver, monkeypatch):
        """
        There used to be a button here offering the passages instead.  An
        error that carries a way to not be an error is not an error.
        """
        # Given a model that fails
        monkeypatch.setattr(service, "build_agent",
                            raising(RuntimeError("429 RESOURCE_EXHAUSTED")))

        # When the turn runs
        events = await collect("Prone condition", saver)

        # Then the error says only what went wrong
        error = next(e for e in events if e["type"] == "error")
        assert set(error) == {"type", "message"}

    @pytest.mark.asyncio
    async def test_given_a_working_model_when_run_then_a_whole_turns_events_arrive(
            self, graph, stub_model, saver):
        # Given the scripted model
        # When a turn runs
        events = await collect("Prone condition", saver)
        kinds = [event["type"] for event in events]

        # Then the search, the answer and its citations all happen
        for expected in ("tool_start", "tool_end", "token", "citations", "done"):
            assert expected in kinds
        assert "error" not in kinds

    @pytest.mark.asyncio
    async def test_given_a_finished_answer_when_it_ends_then_it_cites_the_book(
            self, graph, stub_model, saver):
        """
        Citations are driven by the answer, so one that resolves proves the
        whole chain: search, answer, id, lookup.
        """
        # Given a turn
        # When it finishes
        events = await collect("Prone condition", saver)

        # Then the citations resolve from what was actually said
        citations = next(e for e in events
                         if e["type"] == "citations")["citations"]
        assert citations
        assert all(c["section_id"] for c in citations)

    @pytest.mark.asyncio
    async def test_given_any_turn_when_it_ends_then_done_names_the_thread(
            self, graph, stub_model, saver):
        # Given a turn
        # When it finishes
        events = await collect("Prone condition", saver)

        # Then the last event tells the browser which thread to keep using
        assert events[-1] == {"type": "done", "thread_id": "test"}


class TestHistory:
    """The stored turns of one thread, for a UI reopening it."""

    @pytest.mark.asyncio
    async def test_given_a_stored_thread_when_read_then_the_turns_come_back(
            self, graph, stub_model, saver):
        # Given a thread with one turn in it
        await answer(saver, "kept", "Prone condition")

        # When it is read back
        turns = await service.history("kept", saver)

        # Then the question opens it, with its answer's citations resolved
        assert turns[0] == {"role": "user", "content": "Prone condition"}
        assert turns[1]["role"] == "assistant"
        assert turns[1]["citations"]

    @pytest.mark.asyncio
    async def test_given_a_thread_nobody_used_when_read_then_it_is_empty(self, saver):
        # Given an id nothing was stored under
        # When it is read back
        # Then the route can answer 404 from the emptiness
        assert await service.history("never-used", saver) == []


class TestThreads:
    """Every conversation on disk, pinned first and newest first within that."""

    @pytest.mark.asyncio
    async def test_given_two_conversations_when_listed_then_the_newest_leads(
            self, graph, stub_model, saver, store):
        # Given two conversations, one after the other
        await answer(saver, "older", "Prone condition")
        await answer(saver, "newer", "Restrained condition")

        # When they are listed
        listed = await service.threads(saver, store)

        # Then the most recent is first
        assert [t["thread_id"] for t in listed] == ["newer", "older"]

    @pytest.mark.asyncio
    async def test_given_a_pinned_conversation_when_listed_then_it_sorts_above(
            self, graph, stub_model, saver, store):
        """
        Newest-first is the right default and the wrong answer for the three
        conversations someone keeps coming back to.
        """
        # Given two conversations with the older one pinned
        await answer(saver, "older", "Prone condition")
        await answer(saver, "newer", "Restrained condition")
        await service.set_pinned(store, "older", True)

        # When they are listed
        listed = await service.threads(saver, store)

        # Then the pin outranks the ordering
        assert [t["thread_id"] for t in listed] == ["older", "newer"]
        assert [t["pinned"] for t in listed] == [True, False]

    @pytest.mark.asyncio
    async def test_given_no_store_when_listed_then_nothing_is_pinned(
            self, graph, stub_model, saver):
        """The pins are a second store, and a caller may not have opened one."""
        # Given a conversation and no store to ask
        await answer(saver, "alone")

        # When the threads are listed
        listed = await service.threads(saver)

        # Then the listing still works, with nothing pinned
        assert [t["pinned"] for t in listed] == [False]

    @pytest.mark.asyncio
    async def test_given_a_conversation_when_listed_then_it_is_titled_by_its_question(
            self, graph, stub_model, saver):
        # Given a conversation opened with a long question
        question = "What happens to a creature that " + "really " * 20 + "falls?"
        await answer(saver, "titled", question)

        # When it is listed
        listed, = await service.threads(saver)

        # Then the title is the question, cut at a word
        assert listed["title"].startswith("What happens to a creature")
        assert listed["title"].endswith("…")
        assert len(listed["title"]) <= 61


class TestPinned:
    """The pinned thread ids."""

    @pytest.mark.asyncio
    async def test_given_no_store_when_asked_then_nothing_is_pinned(self):
        # Given no store at all
        # When the pins are read
        # Then the absence is answered rather than raised
        assert await service.pinned(None) == set()


class TestSetPinned:
    """Pinning and unpinning one conversation."""

    @pytest.mark.asyncio
    async def test_given_a_pin_when_removed_then_the_row_is_deleted(
            self, graph, stub_model, saver, store):
        """A pin is its own presence; the value carries nothing the key does not."""
        # Given a pinned conversation
        await answer(saver, "kept")
        await service.set_pinned(store, "kept", True)
        assert await service.pinned(store) == {"kept"}

        # When it is unpinned
        await service.set_pinned(store, "kept", False)

        # Then the row is gone, rather than holding a false
        assert await service.pinned(store) == set()
        assert await store.asearch(service.PINS) == []


class TestForget:
    """Dropping one conversation and everything checkpointed under it."""

    @pytest.mark.asyncio
    async def test_given_a_conversation_when_deleted_then_nothing_of_it_remains(
            self, graph, stub_model, saver):
        """
        There is no thread table, so dropping the checkpoints is what
        deleting a conversation *is*.
        """
        # Given a stored conversation
        await answer(saver, "doomed")
        assert [t["thread_id"] for t in await service.threads(saver)] == ["doomed"]

        # When it is deleted
        deleted = await service.forget("doomed", saver)

        # Then it is gone from the listing and from the history
        assert deleted is True
        assert await service.threads(saver) == []
        assert await service.history("doomed", saver) == []

    @pytest.mark.asyncio
    async def test_given_a_pinned_conversation_when_deleted_then_the_pin_goes_too(
            self, graph, stub_model, saver, store):
        """Otherwise the pin is a row nothing reads and nothing cleans up."""
        # Given a pinned conversation
        await answer(saver, "doomed")
        await service.set_pinned(store, "doomed", True)

        # When it is deleted
        await service.forget("doomed", saver, store)

        # Then its pin went with it
        assert await service.pinned(store) == set()

    @pytest.mark.asyncio
    async def test_given_an_id_nobody_used_when_deleted_then_it_is_not_a_delete(
            self, saver):
        """So the route can answer 404 rather than reporting a success."""
        # Given an id nothing was stored under
        # When it is deleted
        # Then nothing was deleted, and the caller is told
        assert await service.forget("never-used", saver) is False
