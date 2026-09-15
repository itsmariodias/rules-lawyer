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


class TestFromUpdate:
    """The tool node's state write, flattened into a ``tool_end`` event."""

    @staticmethod
    def _update(**kwargs):
        from langchain_core.messages import ToolMessage

        return {"tools": {"messages": [
            ToolMessage(content="…", tool_call_id="c1", name="query_srd_graph",
                        **kwargs)]}}

    def test_given_an_artifact_when_read_then_the_outcome_reaches_the_browser(
            self):
        """
        Without it the trace can only say a call finished, so a refused query
        and a perfect one draw the same grey dot.
        """
        # Given a tool result carrying the status and summary a tool attaches
        update = self._update(artifact={"status": "ok", "summary": "12 rows"})

        # When it is flattened
        [event] = service._from_update(update)

        # Then what came back is on the event, not only how long it was
        assert event["status"] == "ok"
        assert event["summary"] == "12 rows"

    def test_given_a_refusal_when_read_then_it_is_not_reported_as_success(self):
        # Given a tool that refused to run
        update = self._update(artifact={"status": "refused",
                                        "summary": "refused"})

        # When it is flattened
        [event] = service._from_update(update)

        # Then the refusal survives to the trace
        assert event["status"] == "refused"

    def test_given_a_tool_that_raised_when_read_then_it_is_marked_failed(self):
        """
        The tools catch their own errors, but one that does not has no
        artifact at all, and LangChain marks the message instead.
        """
        # Given a tool result LangChain marked as an error
        update = self._update(status="error")

        # When it is flattened
        [event] = service._from_update(update)

        # Then the absent artifact does not read as a successful call
        assert event["status"] == "failed"

    def test_given_no_artifact_when_read_then_the_event_is_still_whole(self):
        """A tool written without one must not break the trace."""
        # Given a plain tool result
        update = self._update()

        # When it is flattened
        [event] = service._from_update(update)

        # Then it is assumed to have worked, and claims no outcome
        assert event["status"] == "ok"
        assert event["summary"] is None
        assert event["id"] == "c1"


class TestTurnsOf:
    """A stored conversation, as the turns a UI draws."""

    @staticmethod
    def _turn(question: str, call_id: str, query: str, answer: str,
              artifact: dict | None = None):
        """One complete turn: a question, a search, its result, an answer."""
        from langchain_core.messages import (AIMessage, HumanMessage,
                                             ToolMessage)
        if artifact is None:
            artifact = {"status": "ok", "summary": "3 passages"}
        return [
            HumanMessage(content=question),
            AIMessage(content="", tool_calls=[{"name": "search_srd",
                                               "args": {"query": query},
                                               "id": call_id}]),
            ToolMessage(content="[1.1] …", tool_call_id=call_id,
                        name="search_srd", artifact=artifact),
            AIMessage(content=answer),
        ]

    def test_given_a_stored_turn_when_read_then_its_lookup_comes_with_it(self):
        """
        Dropped here, an answer reopened from the list had no retrieval under
        it and the trace read as something that had never happened.
        """
        # Given one complete turn
        messages = self._turn("Prone?", "c1", "prone", "It is [11.2.114].")

        # When it is read back
        turns = service.turns_of(messages)

        # Then the lookup is on the answer, finished, with its outcome
        assert [t["role"] for t in turns] == ["user", "assistant"]
        assert turns[1]["tools"] == [{
            "id": "c1", "name": "search_srd", "args": {"query": "prone"},
            "done": True, "status": "ok", "summary": "3 passages",
            "subject": None}]

    def test_given_two_turns_when_read_then_each_keeps_its_own_lookups(self):
        """A lookup belongs to the turn that made it, not to the thread."""
        # Given two complete turns in one conversation
        messages = (self._turn("Prone?", "c1", "prone", "First.")
                    + self._turn("Restrained?", "c2", "restrained", "Second."))

        # When they are read back
        answers = [t for t in service.turns_of(messages)
                   if t["role"] == "assistant"]

        # Then neither turn carries the other's searches
        assert [len(a["tools"]) for a in answers] == [1, 1]
        assert answers[0]["tools"][0]["id"] == "c1"
        assert answers[1]["tools"][0]["id"] == "c2"

    def test_given_a_turn_that_never_answered_when_read_then_it_leaks_nothing(
            self):
        """
        A turn that ended in an error leaves its lookups behind. They belong
        to that turn, not to the next question.
        """
        # Given a turn whose search never reached an answer
        from langchain_core.messages import AIMessage, HumanMessage

        messages = [
            HumanMessage(content="Prone?"),
            AIMessage(content="", tool_calls=[{"name": "search_srd",
                                               "args": {"query": "prone"},
                                               "id": "lost"}]),
        ] + self._turn("Restrained?", "c2", "restrained", "Second.")

        # When it is read back
        answers = [t for t in service.turns_of(messages)
                   if t["role"] == "assistant"]

        # Then the abandoned search is not credited to the question after it
        assert [c["id"] for c in answers[0]["tools"]] == ["c2"]

    def test_given_several_lookups_when_read_then_they_keep_their_order(self):
        # Given a turn that searched, then read a section
        from langchain_core.messages import (AIMessage, HumanMessage,
                                             ToolMessage)

        messages = [
            HumanMessage(content="Prone?"),
            AIMessage(content="", tool_calls=[
                {"name": "search_srd", "args": {}, "id": "a"}]),
            ToolMessage(content="…", tool_call_id="a", name="search_srd"),
            AIMessage(content="", tool_calls=[
                {"name": "get_srd_section", "args": {}, "id": "b"}]),
            ToolMessage(content="…", tool_call_id="b", name="get_srd_section"),
            AIMessage(content="Answer."),
        ]

        # When it is read back
        [_, answer] = service.turns_of(messages)

        # Then the trace reads in the order the agent worked
        assert [c["id"] for c in answer["tools"]] == ["a", "b"]

    def test_given_a_result_with_no_artifact_when_read_then_it_reads_as_done(
            self):
        """Conversations stored before the tools carried one."""
        # Given a turn whose tool result predates the artifact
        messages = self._turn("Prone?", "c1", "prone", "Answer.",
                              artifact={})

        # When it is read back
        [_, answer] = service.turns_of(messages)

        # Then it is a finished call with an unknown outcome, not a broken one
        assert answer["tools"][0]["done"] is True
        assert answer["tools"][0]["status"] == "ok"
        assert answer["tools"][0]["summary"] is None

    def test_given_a_tool_that_raised_when_read_then_it_is_marked_failed(self):
        # Given a turn whose tool LangChain marked as an error
        from langchain_core.messages import (AIMessage, HumanMessage,
                                             ToolMessage)

        messages = [
            HumanMessage(content="Prone?"),
            AIMessage(content="", tool_calls=[
                {"name": "query_srd_graph", "args": {}, "id": "a"}]),
            ToolMessage(content="boom", tool_call_id="a",
                        name="query_srd_graph", status="error"),
            AIMessage(content="Answer."),
        ]

        # When it is read back
        [_, answer] = service.turns_of(messages)

        # Then the failure survives being reopened
        assert answer["tools"][0]["status"] == "failed"

    def test_given_a_blank_answer_when_read_then_no_turn_is_made_for_it(self):
        # Given a conversation whose answer is empty
        from langchain_core.messages import AIMessage, HumanMessage

        messages = [HumanMessage(content="Prone?"), AIMessage(content="  ")]

        # When it is read back
        turns = service.turns_of(messages)

        # Then only the question is a turn
        assert [t["role"] for t in turns] == ["user"]


class TestWrittenAt:
    """When each message in a thread was first written."""

    def test_given_a_dated_conversation_when_read_then_each_turn_carries_its_moment(
            self):
        """
        The checkpoint's own timestamp, not anything the model said, so a
        reopened conversation is dated by when it happened.
        """
        # Given a conversation whose messages were stamped as they were stored
        from langchain_core.messages import AIMessage, HumanMessage

        asked = HumanMessage(content="Prone?", id="h1")
        answered = AIMessage(content="It does.", id="a1")
        when = {"h1": "2026-09-14T08:57:45+00:00",
                "a1": "2026-09-14T08:57:58+00:00"}

        # When the turns are read back
        turns = service.turns_of([asked, answered], when)

        # Then each is dated
        assert [t["at"] for t in turns] == [when["h1"], when["a1"]]

    def test_given_an_undated_conversation_when_read_then_the_turns_still_come_back(
            self):
        """One stored before this was read is still a conversation."""
        # Given messages with nothing known about when they were written
        from langchain_core.messages import AIMessage, HumanMessage

        messages = [HumanMessage(content="Prone?"), AIMessage(content="Yes.")]

        # When the turns are read back
        turns = service.turns_of(messages)

        # Then they are simply undated
        assert [t["at"] for t in turns] == [None, None]


class TestFindResult:
    """One lookup's stored result, by the id that joins it to its call."""

    @staticmethod
    def _messages(*results):
        from langchain_core.messages import AIMessage, ToolMessage

        return [AIMessage(content="")] + [
            ToolMessage(content=body, tool_call_id=call_id, name="search_srd")
            for call_id, body in results]

    def test_given_a_call_id_when_looked_up_then_its_own_result_comes_back(self):
        """
        The whole of it. The model was given the whole thing, and a reader
        asking to see what the model saw should get the same.
        """
        # Given a conversation with two lookups in it
        messages = self._messages(("a", "first result"), ("b", "second result"))

        # When one is looked up
        found = service.find_result(messages, "b")

        # Then it is that one, not the other
        assert found["content"] == "second result"
        assert found["id"] == "b"
        assert found["truncated"] is False

    def test_given_an_unknown_call_when_looked_up_then_it_is_absent(self):
        # Given a conversation
        # When a call that is not in it is looked up
        # Then the absence is answered, so the route can say 404
        assert service.find_result(self._messages(("a", "x")), "zzz") is None

    def test_given_an_enormous_result_when_looked_up_then_it_is_capped(self):
        """A wide query renders a whole table, and a browser has to draw it."""
        # Given a result longer than anything worth sending
        messages = self._messages(("a", "x" * (service.RESULT_CHARS + 500)))

        # When it is looked up
        found = service.find_result(messages, "a")

        # Then it is cut, and says so rather than reading as the whole result
        assert len(found["content"]) == service.RESULT_CHARS
        assert found["truncated"] is True


class TestNameMissingSubjects:
    """What a stored lookup looked at, where the tool did not say."""

    @staticmethod
    def _turn(**call):
        return [{"role": "assistant", "content": "…", "tools": [
            {"id": "a", "name": "get_srd_section", "args": {},
             "done": True, "status": "ok", "summary": None,
             "subject": None, **call}]}]

    def test_given_a_legacy_lookup_when_read_then_the_graph_names_it(
            self, graph):
        """
        A conversation answered before the tools carried an artifact has only
        the dotted id it was called with, and `11.2.114` names nothing.
        """
        # Given a stored lookup with an id and no subject
        turns = self._turn(args={"section_id": "11.2.114"})

        # When the missing subjects are filled in
        service.name_missing_subjects(turns)

        # Then the row can say what was read
        assert turns[0]["tools"][0]["subject"] == "Prone [Condition]"

    def test_given_a_lookup_that_named_itself_when_read_then_it_is_left_alone(
            self, graph):
        # Given a lookup whose tool already said what it looked at
        turns = self._turn(args={"section_id": "11.2.114"},
                           subject="Something else")

        # When the missing subjects are filled in
        service.name_missing_subjects(turns)

        # Then what the tool said stands
        assert turns[0]["tools"][0]["subject"] == "Something else"

    def test_given_a_lookup_with_no_id_when_read_then_nothing_is_invented(self):
        """A search argument is the words someone chose; there is nothing to
        look up and no round trip to make."""
        # Given a search, which carries no section id
        turns = self._turn(name="search_srd", args={"query": "prone"})

        # When the missing subjects are filled in
        service.name_missing_subjects(turns)

        # Then it is untouched, without reaching the graph
        assert turns[0]["tools"][0]["subject"] is None

    def test_given_an_id_that_resolves_to_nothing_when_read_then_it_stays_empty(
            self, graph):
        """A re-parse can drop an id a stored conversation still names."""
        # Given a lookup of a section that is no longer there
        turns = self._turn(args={"section_id": "999.999"})

        # When the missing subjects are filled in
        service.name_missing_subjects(turns)

        # Then the row falls back to the id rather than inventing a heading
        assert turns[0]["tools"][0]["subject"] is None

    def test_given_one_id_read_twice_when_filled_then_it_is_looked_up_once(
            self, monkeypatch):
        """A long conversation revisits the same section repeatedly."""
        # Given two lookups of the same section, and a counted resolver
        calls = []
        monkeypatch.setattr(
            service.retrieval, "get_section",
            lambda section_id: calls.append(section_id) or None)
        turns = (self._turn(args={"section_id": "11.2.114"})
                 + self._turn(args={"section_id": "11.2.114"}))

        # When the missing subjects are filled in
        service.name_missing_subjects(turns)

        # Then the graph was asked once
        assert calls == ["11.2.114"]


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
        assert turns[0]["role"] == "user"
        assert turns[0]["content"] == "Prone condition"
        # and dated, from the checkpoint that stored it
        assert turns[0]["at"]
        assert turns[1]["role"] == "assistant"
        assert turns[1]["citations"]

    @pytest.mark.asyncio
    async def test_given_a_thread_nobody_used_when_read_then_it_is_empty(self, saver):
        # Given an id nothing was stored under
        # When it is read back
        # Then the route can answer 404 from the emptiness
        assert await service.history("never-used", saver) == []


class TestLastQuestion:
    """The final question in a conversation, and the message it is."""

    def test_given_a_conversation_when_read_then_the_latest_question_wins(self):
        # Given a conversation of two answered turns
        from langchain_core.messages import AIMessage, HumanMessage
        messages = [HumanMessage(content="Prone?"), AIMessage(content="Yes."),
                    HumanMessage(content="Restrained?"), AIMessage(content="No.")]

        # When its last question is found
        found = service.last_question(messages)

        # Then it is the one a retry would ask again, named by its own id
        assert found == ("Restrained?", messages[2].id)

    def test_given_a_turn_that_failed_when_read_then_the_question_still_stands(
            self):
        """A turn the model could not answer stores the question and nothing
        else, which is exactly the turn somebody retries."""
        # Given a question with no answer under it
        from langchain_core.messages import HumanMessage
        messages = [HumanMessage(content="Prone?")]

        # When its last question is found
        # Then the failure did not take it with it
        assert service.last_question(messages)[0] == "Prone?"

    def test_given_nothing_asked_when_read_then_there_is_nothing_to_retry(self):
        # Given a conversation with no question in it
        # When its last question is found
        # Then the route has its 404
        assert service.last_question([]) is None


class TestRewind:
    """Undoing the last turn, which is what makes a retry a retry."""

    @pytest.mark.asyncio
    async def test_given_a_later_turn_when_rewound_then_it_branches_before_it(
            self, graph, stub_model, saver):
        """
        Re-asking without this would append, and the conversation would hold
        the same question twice for as long as it existed.
        """
        # Given a conversation of two answered turns
        await answer(saver, "again", "Prone condition")
        await answer(saver, "again", "Restrained condition")

        # When the last of them is rewound and asked again
        text, checkpoint_id = await service.rewind("again", saver)
        async for _ in service.stream_turn(text, "again", saver, checkpoint_id):
            pass

        # Then the question came back, and it was asked once
        assert text == "Restrained condition"
        assert checkpoint_id is not None
        turns = await service.history("again", saver)
        assert [t["content"] for t in turns if t["role"] == "user"] == [
            "Prone condition", "Restrained condition"]

    @pytest.mark.asyncio
    async def test_given_the_only_turn_when_rewound_then_it_branches_before_it(
            self, graph, stub_model, saver):
        """
        The first question is not a special case: the graph checkpoints a
        step before the input reaches it, so even the opening turn has an
        empty state to branch from.  The thread id survives the rewind either
        way, which is what the browser is holding and what a pin is keyed on.
        """
        # Given a conversation of one answered turn
        await answer(saver, "first", "Prone condition")

        # When it is rewound and asked again
        text, checkpoint_id = await service.rewind("first", saver)
        async for _ in service.stream_turn(text, "first", saver, checkpoint_id):
            pass

        # Then the conversation is still that one question, under its own id
        turns = await service.history("first", saver)
        assert [t["content"] for t in turns if t["role"] == "user"] == [
            "Prone condition"]
        assert [t["thread_id"] for t in await service.threads(saver)] == ["first"]

    @pytest.mark.asyncio
    async def test_given_a_thread_nobody_used_when_rewound_then_it_is_nothing(
            self, stub_model, saver):
        # Given an id nothing was stored under
        # When it is rewound
        # Then there is no question to ask again
        assert await service.rewind("never-used", saver) is None


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
