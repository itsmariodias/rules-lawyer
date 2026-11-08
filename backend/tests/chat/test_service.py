from __future__ import annotations

import asyncio

import pytest

from dnd_graph_rag.chat import service, titles


async def answer(saver, thread_id: str, question: str = "Prone condition") -> None:
    """Run one stub turn and return the stored thread id."""
    async for _ in service.stream_turn(question, thread_id, saver):
        pass


def raising(exc: Exception):
    """A ``build_agent`` replacement that raises ``exc``."""
    def build(_checkpointer):
        raise exc

    return build


async def collect(message, saver) -> list[dict]:
    return [event async for event in
            service.stream_turn(message, "test", saver)]


class TestCitation:
    def test_given_a_mix_of_brackets_when_matched_then_only_dotted_ids_count(self):
        # Given an answer carrying both kinds of bracket
        text = "Prone [11.2.114] and see [below] and [3] and [4.8.2.3]."

        # When the citations are found
        found = service.CITATION.findall(text)

        # Then only the dotted ids are citations
        assert found == ["11.2.114", "4.8.2.3"]


class TestResolveCitations:
    def test_given_an_invented_id_when_resolved_then_it_is_dropped(self, graph):
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
    def test_given_a_missing_key_when_explained_then_the_fix_is_in_the_sentence(self):
        # Given the error a missing key raises
        # When it is explained
        explained = service._explain(RuntimeError("GOOGLE_API_KEY is not set"))

        # Then it says where to put one
        assert "GOOGLE_API_KEY is not set" in explained
        assert ".env" in explained

    def test_given_a_rejected_key_when_explained_then_it_is_not_the_providers_json(self):
        """Google's invalid-key error is about 600 characters of JSON."""
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
    @staticmethod
    def _update(**kwargs):
        from langchain_core.messages import ToolMessage

        return {"tools": {"messages": [
            ToolMessage(content="…", tool_call_id="c1", name="query_srd_graph",
                        **kwargs)]}}

    def test_given_an_artifact_when_read_then_the_outcome_reaches_the_browser(
            self):
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
        # Given a tool result LangChain marked as an error
        update = self._update(status="error")

        # When it is flattened
        [event] = service._from_update(update)

        # Then the absent artifact does not read as a successful call
        assert event["status"] == "failed"

    def test_given_no_artifact_when_read_then_the_event_is_still_whole(self):
        # Given a plain tool result
        update = self._update()

        # When it is flattened
        [event] = service._from_update(update)

        # Then it is assumed to have worked, and claims no outcome
        assert event["status"] == "ok"
        assert event["summary"] is None
        assert event["id"] == "c1"


class TestUsageOf:
    @staticmethod
    def _call(content: str, input_tokens: int, output_tokens: int):
        from langchain_core.messages import AIMessage
        return AIMessage(content=content, usage_metadata={
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens})

    def test_given_several_calls_when_counted_then_they_are_summed(self):
        # Given a turn of three model calls
        messages = [self._call("", 4000, 20), self._call("", 5200, 35),
                    self._call("It is [11.2.114].", 6100, 410)]

        # When what it cost is counted
        usage = service.usage_of(messages)

        # Then every call is in the sum, and the calls are counted
        assert usage == {"input": 15300, "output": 465, "total": 15765,
                         "calls": 3}

    def test_given_other_messages_when_counted_then_only_model_calls_count(self):
        # Given a question and a tool result among the calls
        from langchain_core.messages import HumanMessage, ToolMessage
        messages = [HumanMessage(content="Prone?"), self._call("", 100, 5),
                    ToolMessage(content="[1.1] …", tool_call_id="c1")]

        # When what it cost is counted
        # Then neither is mistaken for a call
        assert service.usage_of(messages)["calls"] == 1

    def test_given_no_counts_when_counted_then_there_is_no_usage(self):
        # Given calls that carry no counts, as a conversation stored before might
        from langchain_core.messages import AIMessage

        # When what it cost is counted
        # Then there is no figure at all
        assert service.usage_of([AIMessage(content="It is.")]) is None
        assert service.usage_of([]) is None


class TestTurnsOf:
    @staticmethod
    def _turn(question: str, call_id: str, query: str, answer: str,
              artifact: dict | None = None):
        """Messages for one turn: question, search call, result, answer."""
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

    def test_given_two_turns_when_read_then_each_counts_only_its_own_calls(self):
        # Given two turns, every call in them counted
        messages = (self._turn("Prone?", "c1", "prone", "It is [11.2.114].")
                    + self._turn("Grappled?", "c2", "grappled", "It is [11.2.60]."))
        for message in messages:
            if message.type == "ai":
                message.usage_metadata = {"input_tokens": 1000,
                                          "output_tokens": 10,
                                          "total_tokens": 1010}

        # When they are read back
        answers = [t for t in service.turns_of(messages) if t["role"] == "assistant"]

        # Then each answer carries its own two calls, not the turn before's
        assert [a["usage"] for a in answers] == [
            {"input": 2000, "output": 20, "total": 2020, "calls": 2}] * 2

    def test_given_two_turns_when_read_then_each_keeps_its_own_lookups(self):
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
    def test_given_a_dated_conversation_when_read_then_each_turn_carries_its_moment(
            self):
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
        # Given messages with nothing known about when they were written
        from langchain_core.messages import AIMessage, HumanMessage

        messages = [HumanMessage(content="Prone?"), AIMessage(content="Yes.")]

        # When the turns are read back
        turns = service.turns_of(messages)

        # Then they are simply undated
        assert [t["at"] for t in turns] == [None, None]


class TestFindResult:
    @staticmethod
    def _messages(*results):
        from langchain_core.messages import AIMessage, ToolMessage

        return [AIMessage(content="")] + [
            ToolMessage(content=body, tool_call_id=call_id, name="search_srd")
            for call_id, body in results]

    def test_given_a_call_id_when_looked_up_then_its_own_result_comes_back(self):
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
        # Given a result longer than anything worth sending
        messages = self._messages(("a", "x" * (service.RESULT_CHARS + 500)))

        # When it is looked up
        found = service.find_result(messages, "a")

        # Then it is cut, and says so rather than reading as the whole result
        assert len(found["content"]) == service.RESULT_CHARS
        assert found["truncated"] is True


class TestNameMissingSubjects:
    @staticmethod
    def _turn(**call):
        return [{"role": "assistant", "content": "…", "tools": [
            {"id": "a", "name": "get_srd_section", "args": {},
             "done": True, "status": "ok", "summary": None,
             "subject": None, **call}]}]

    def test_given_a_legacy_lookup_when_read_then_the_graph_names_it(
            self, graph):
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
        # Given a search, which carries no section id
        turns = self._turn(name="search_srd", args={"query": "prone"})

        # When the missing subjects are filled in
        service.name_missing_subjects(turns)

        # Then it is untouched, without reaching the graph
        assert turns[0]["tools"][0]["subject"] is None

    def test_given_an_id_that_resolves_to_nothing_when_read_then_it_stays_empty(
            self, graph):
        # Given a lookup of a section that is no longer there
        turns = self._turn(args={"section_id": "999.999"})

        # When the missing subjects are filled in
        service.name_missing_subjects(turns)

        # Then the row falls back to the id rather than inventing a heading
        assert turns[0]["tools"][0]["subject"] is None

    def test_given_one_id_read_twice_when_filled_then_it_is_looked_up_once(
            self, monkeypatch):
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
    @pytest.mark.asyncio
    async def test_given_a_stalled_stream_when_run_then_the_turn_fails(self):
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
    @pytest.mark.asyncio
    async def test_given_a_turn_when_run_then_what_it_cost_comes_before_done(
            self, graph, stub_model, saver):
        # Given the scripted model, which searches and then answers
        # When the turn runs
        events = await collect("Prone condition", saver)

        # Then both calls are counted, once, ahead of the end of the turn
        kinds = [e["type"] for e in events if e["type"] != "token"]
        usage = next(e for e in events if e["type"] == "usage")
        assert kinds[-3:] == ["usage", "citations", "done"]
        assert usage["calls"] == 2
        assert usage["total"] == usage["input"] + usage["output"]

    @pytest.mark.asyncio
    async def test_given_a_failed_model_when_run_then_the_error_is_the_answer(
            self, graph, saver, monkeypatch):
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
    @pytest.mark.asyncio
    async def test_given_a_later_turn_when_rewound_then_it_branches_before_it(
            self, graph, stub_model, saver):
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
        The graph checkpoints once before the input, so the first turn has an
        empty state to branch from.
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

    @pytest.mark.asyncio
    async def test_given_a_stored_title_when_listed_then_it_names_the_conversation(
            self, graph, stub_model, saver, store):
        # Given two conversations, only one of them titled
        await answer(saver, "titled", "What exactly does the Prone condition do?")
        await answer(saver, "untitled", "Restrained condition")
        await titles.remember(store, "titled", "Prone condition effects")

        # When they are listed
        listed = {t["thread_id"]: t["title"] for t in await service.threads(saver, store)}

        # Then the title is used where there is one, and the question elsewhere
        assert listed == {"titled": "Prone condition effects",
                          "untitled": "Restrained condition"}


class TestPinned:
    @pytest.mark.asyncio
    async def test_given_no_store_when_asked_then_nothing_is_pinned(self):
        # Given no store at all
        # When the pins are read
        # Then the absence is answered rather than raised
        assert await service.pinned(None) == set()

    @pytest.mark.asyncio
    async def test_given_many_pins_when_asked_then_every_one_comes_back(self, store):
        """``BaseStore.asearch`` returns ten results by default."""
        # Given more pins than a default page holds
        for n in range(11):
            await service.set_pinned(store, f"t{n}", True)

        # When the pins are read
        # Then none is missing
        assert await service.pinned(store) == {f"t{n}" for n in range(11)}


class TestSetPinned:
    @pytest.mark.asyncio
    async def test_given_a_pin_when_removed_then_the_row_is_deleted(
            self, graph, stub_model, saver, store):
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
    @pytest.mark.asyncio
    async def test_given_a_conversation_when_deleted_then_nothing_of_it_remains(
            self, graph, stub_model, saver):
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
        # Given a pinned conversation
        await answer(saver, "doomed")
        await service.set_pinned(store, "doomed", True)

        # When it is deleted
        await service.forget("doomed", saver, store)

        # Then its pin went with it
        assert await service.pinned(store) == set()

    @pytest.mark.asyncio
    async def test_given_a_titled_conversation_when_deleted_then_the_title_goes_too(
            self, graph, stub_model, saver, store):
        # Given a titled conversation
        await answer(saver, "doomed")
        await titles.remember(store, "doomed", "Prone condition effects")

        # When it is deleted
        await service.forget("doomed", saver, store)

        # Then its title went with it
        assert await titles.titled(store) == {}

    @pytest.mark.asyncio
    async def test_given_an_id_nobody_used_when_deleted_then_it_is_not_a_delete(
            self, saver):
        # Given an id nothing was stored under
        # When it is deleted
        # Then nothing was deleted, and the caller is told
        assert await service.forget("never-used", saver) is False
