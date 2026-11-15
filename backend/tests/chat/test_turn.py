from __future__ import annotations

import asyncio

import pytest

from rules_lawyer.chat import turn
from tests.fakes import FakeChatModel


def raising(exc: Exception):
    """A ``build_agent`` replacement that raises ``exc``."""
    def build(_model, _checkpointer):
        raise exc

    return build


async def collect(message, saver) -> list[dict]:
    return [event async for event in
            turn.stream_turn(message, "test", saver, FakeChatModel())]


@pytest.mark.neo4j
class TestResolveCitations:
    def test_given_an_invented_id_when_resolved_then_it_is_dropped(self, graph):
        # Given an answer citing one real id and one invented one, twice
        text = "Real [11.2.114], invented [99.99.99], and again [11.2.114]."

        # When the citations are resolved
        citations = turn.resolve_citations(text)

        # Then only what resolves survives, once
        assert [c["section_id"] for c in citations] == ["11.2.114"]

    def test_given_no_citations_at_all_when_resolved_then_the_list_is_empty(
            self, graph):
        # Given an answer citing nothing
        # When the citations are resolved
        # Then nothing is invented for it
        assert turn.resolve_citations("No ids here.") == []


class TestExplain:
    def test_given_a_missing_key_when_explained_then_the_fix_is_in_the_sentence(self):
        # Given the error a missing key raises
        # When it is explained
        explained = turn._explain(RuntimeError("GOOGLE_API_KEY is not set"))

        # Then it says where to put one
        assert "GOOGLE_API_KEY is not set" in explained
        assert ".env" in explained

    def test_given_a_rejected_key_when_explained_then_it_is_not_the_providers_json(self):
        """Google's invalid-key error is about 600 characters of JSON."""
        # Given Google's own rejection
        error = RuntimeError("400 INVALID_ARGUMENT {'reason': 'API_KEY_INVALID'}")

        # When it is explained
        # Then the reader gets a sentence rather than a payload
        assert "GOOGLE_API_KEY was rejected" in turn._explain(error)

    def test_given_a_spent_quota_when_explained_then_it_is_named_as_one(self):
        # Given the error a spent free tier raises
        # When it is explained
        explained = turn._explain(RuntimeError("429 RESOURCE_EXHAUSTED: quota"))

        # Then the reader is told the model, not the answer, is the problem
        assert "quota" in explained.lower()

    def test_given_a_stall_when_explained_then_it_says_nothing_arrived(self):
        # Given a timeout
        # When it is explained
        explained = turn._explain(TimeoutError("the model sent nothing for 60s"))

        # Then it says why the turn was ended rather than left hanging
        assert "stopped responding" in explained

    def test_given_an_error_nobody_anticipated_when_explained_then_it_stays_readable(self):
        # Given an enormous unrecognised error
        # When it is explained
        explained = turn._explain(RuntimeError("boom " * 200))

        # Then it is capped at a length someone will still read
        assert len(explained) <= turn.ERROR_CHARS + 1
        assert explained.endswith("…")

    def test_given_a_short_error_when_explained_then_it_is_passed_through_whole(self):
        # Given a short unrecognised error
        # When it is explained
        explained = turn._explain(ValueError("something odd"))

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
        [event] = turn._from_update(update)

        # Then what came back is on the event, not only how long it was
        assert event["status"] == "ok"
        assert event["summary"] == "12 rows"

    def test_given_a_refusal_when_read_then_it_is_not_reported_as_success(self):
        # Given a tool that refused to run
        update = self._update(artifact={"status": "refused",
                                        "summary": "refused"})

        # When it is flattened
        [event] = turn._from_update(update)

        # Then the refusal survives to the trace
        assert event["status"] == "refused"

    def test_given_a_tool_that_raised_when_read_then_it_is_marked_failed(self):
        # Given a tool result LangChain marked as an error
        update = self._update(status="error")

        # When it is flattened
        [event] = turn._from_update(update)

        # Then the absent artifact does not read as a successful call
        assert event["status"] == "failed"

    def test_given_no_artifact_when_read_then_the_event_is_still_whole(self):
        # Given a plain tool result
        update = self._update()

        # When it is flattened
        [event] = turn._from_update(update)

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
        usage = turn.usage_of(messages)

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
        assert turn.usage_of(messages)["calls"] == 1

    def test_given_no_counts_when_counted_then_there_is_no_usage(self):
        # Given calls that carry no counts, as a conversation stored before might
        from langchain_core.messages import AIMessage

        # When what it cost is counted
        # Then there is no figure at all
        assert turn.usage_of([AIMessage(content="It is.")]) is None
        assert turn.usage_of([]) is None


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
            async for _ in turn._until_silent(never_speaks(), 0.05):
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
                turn._until_silent(slow_but_steady(), 0.05)]

        # Then every event arrived
        assert [payload for _, payload in seen] == [0, 1, 2, 3]

    @pytest.mark.asyncio
    async def test_given_a_stream_that_ends_when_run_then_it_ends_cleanly(self):
        # Given a stream that finishes
        async def finishes():
            yield ("messages", 1)

        # When it is run
        seen = [item async for item in turn._until_silent(finishes(), 1)]

        # Then exhaustion is not a timeout
        assert seen == [("messages", 1)]


@pytest.mark.neo4j
class TestStreamTurn:
    @pytest.mark.asyncio
    async def test_given_a_turn_when_run_then_what_it_cost_comes_before_done(
            self, graph, saver):
        # Given the fake model, which searches and then answers
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
        monkeypatch.setattr(turn, "build_agent",
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
        monkeypatch.setattr(turn, "build_agent",
                            raising(RuntimeError("429 RESOURCE_EXHAUSTED")))

        # When the turn runs
        events = await collect("Prone condition", saver)

        # Then the error says only what went wrong
        error = next(e for e in events if e["type"] == "error")
        assert set(error) == {"type", "message"}

    @pytest.mark.asyncio
    async def test_given_a_working_model_when_run_then_a_whole_turns_events_arrive(
            self, graph, saver):
        # Given the fake model
        # When a turn runs
        events = await collect("Prone condition", saver)
        kinds = [event["type"] for event in events]

        # Then the search, the answer and its citations all happen
        for expected in ("tool_start", "tool_end", "token", "citations", "done"):
            assert expected in kinds
        assert "error" not in kinds

    @pytest.mark.asyncio
    async def test_given_a_finished_answer_when_it_ends_then_it_cites_the_book(
            self, graph, saver):
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
            self, graph, saver):
        # Given a turn
        # When it finishes
        events = await collect("Prone condition", saver)

        # Then the last event tells the browser which thread to keep using
        assert events[-1] == {"type": "done", "thread_id": "test"}
