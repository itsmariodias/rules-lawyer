from __future__ import annotations

import pytest

from rules_lawyer.chat import threads


class TestTurnsOf:
    @staticmethod
    def _turn(question: str, call_id: str, query: str, answer: str,
              artifact: dict | None = None):
        """Messages for one turn: question, search call, result, answer."""
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
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
        messages = self._turn("Prone?", "c1", "prone", "It is.")

        # When it is read back
        turns = threads.turns_of(messages)

        # Then the lookup is on the answer, finished, with its outcome
        assert [t["role"] for t in turns] == ["user", "assistant"]
        assert turns[1]["tools"] == [{
            "id": "c1", "name": "search_srd", "args": {"query": "prone"},
            "done": True, "status": "ok", "summary": "3 passages",
            "subject": None}]

    def test_given_two_turns_when_read_then_each_counts_only_its_own_calls(self):
        # Given two turns, every call in them counted
        messages = (self._turn("Prone?", "c1", "prone", "It is.")
                    + self._turn("Grappled?", "c2", "grappled", "It is."))
        for message in messages:
            if message.type == "ai":
                message.usage_metadata = {"input_tokens": 1000,
                                          "output_tokens": 10,
                                          "total_tokens": 1010}

        # When they are read back
        answers = [t for t in threads.turns_of(messages) if t["role"] == "assistant"]

        # Then each answer carries its own two calls, not the turn before's
        assert [a["usage"] for a in answers] == [
            {"input": 2000, "output": 20, "total": 2020, "calls": 2}] * 2

    def test_given_two_turns_when_read_then_each_keeps_its_own_lookups(self):
        # Given two complete turns in one conversation
        messages = (self._turn("Prone?", "c1", "prone", "First.")
                    + self._turn("Restrained?", "c2", "restrained", "Second."))

        # When they are read back
        answers = [t for t in threads.turns_of(messages)
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
        answers = [t for t in threads.turns_of(messages)
                   if t["role"] == "assistant"]

        # Then the abandoned search is not credited to the question after it
        assert [c["id"] for c in answers[0]["tools"]] == ["c2"]

    def test_given_several_lookups_when_read_then_they_keep_their_order(self):
        # Given a turn that searched, then read a section
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

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
        [_, answer] = threads.turns_of(messages)

        # Then the trace reads in the order the agent worked
        assert [c["id"] for c in answer["tools"]] == ["a", "b"]

    def test_given_a_result_with_no_artifact_when_read_then_it_reads_as_done(
            self):
        # Given a turn whose tool result predates the artifact
        messages = self._turn("Prone?", "c1", "prone", "Answer.",
                              artifact={})

        # When it is read back
        [_, answer] = threads.turns_of(messages)

        # Then it is a finished call with an unknown outcome, not a broken one
        assert answer["tools"][0]["done"] is True
        assert answer["tools"][0]["status"] == "ok"
        assert answer["tools"][0]["summary"] is None

    def test_given_a_tool_that_raised_when_read_then_it_is_marked_failed(self):
        # Given a turn whose tool LangChain marked as an error
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        messages = [
            HumanMessage(content="Prone?"),
            AIMessage(content="", tool_calls=[
                {"name": "query_srd_graph", "args": {}, "id": "a"}]),
            ToolMessage(content="boom", tool_call_id="a",
                        name="query_srd_graph", status="error"),
            AIMessage(content="Answer."),
        ]

        # When it is read back
        [_, answer] = threads.turns_of(messages)

        # Then the failure survives being reopened
        assert answer["tools"][0]["status"] == "failed"

    def test_given_a_blank_answer_when_read_then_no_turn_is_made_for_it(self):
        # Given a conversation whose answer is empty
        from langchain_core.messages import AIMessage, HumanMessage

        messages = [HumanMessage(content="Prone?"), AIMessage(content="  ")]

        # When it is read back
        turns = threads.turns_of(messages)

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
        turns = threads.turns_of([asked, answered], when)

        # Then each is dated
        assert [t["at"] for t in turns] == [when["h1"], when["a1"]]

    def test_given_an_undated_conversation_when_read_then_the_turns_still_come_back(
            self):
        # Given messages with nothing known about when they were written
        from langchain_core.messages import AIMessage, HumanMessage

        messages = [HumanMessage(content="Prone?"), AIMessage(content="Yes.")]

        # When the turns are read back
        turns = threads.turns_of(messages)

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
        found = threads.find_result(messages, "b")

        # Then it is that one, not the other
        assert found["content"] == "second result"
        assert found["id"] == "b"
        assert found["truncated"] is False

    def test_given_an_unknown_call_when_looked_up_then_it_is_absent(self):
        # Given a conversation
        # When a call that is not in it is looked up
        # Then the absence is answered, so the route can say 404
        assert threads.find_result(self._messages(("a", "x")), "zzz") is None

    def test_given_an_enormous_result_when_looked_up_then_it_is_capped(self):
        # Given a result longer than anything worth sending
        messages = self._messages(("a", "x" * (threads.RESULT_CHARS + 500)))

        # When it is looked up
        found = threads.find_result(messages, "a")

        # Then it is cut, and says so rather than reading as the whole result
        assert len(found["content"]) == threads.RESULT_CHARS
        assert found["truncated"] is True


class TestNameMissingSubjects:
    @staticmethod
    def _turn(**call):
        return [{"role": "assistant", "content": "…", "tools": [
            {"id": "a", "name": "get_srd_section", "args": {},
             "done": True, "status": "ok", "summary": None,
             "subject": None, **call}]}]

    @pytest.mark.neo4j
    def test_given_a_legacy_lookup_when_read_then_the_graph_names_it(
            self, graph):
        # Given a stored lookup with an id and no subject
        turns = self._turn(args={"section_id": "11.2.114"})

        # When the missing subjects are filled in
        threads.name_missing_subjects(turns)

        # Then the row can say what was read
        assert turns[0]["tools"][0]["subject"] == "Prone [Condition]"

    @pytest.mark.neo4j
    def test_given_a_lookup_that_named_itself_when_read_then_it_is_left_alone(
            self, graph):
        # Given a lookup whose tool already said what it looked at
        turns = self._turn(args={"section_id": "11.2.114"},
                           subject="Something else")

        # When the missing subjects are filled in
        threads.name_missing_subjects(turns)

        # Then what the tool said stands
        assert turns[0]["tools"][0]["subject"] == "Something else"

    def test_given_a_lookup_with_no_id_when_read_then_nothing_is_invented(self):
        # Given a search, which carries no section id
        turns = self._turn(name="search_srd", args={"query": "prone"})

        # When the missing subjects are filled in
        threads.name_missing_subjects(turns)

        # Then it is untouched, without reaching the graph
        assert turns[0]["tools"][0]["subject"] is None

    @pytest.mark.neo4j
    def test_given_an_id_that_resolves_to_nothing_when_read_then_it_stays_empty(
            self, graph):
        # Given a lookup of a section that is no longer there
        turns = self._turn(args={"section_id": "999.999"})

        # When the missing subjects are filled in
        threads.name_missing_subjects(turns)

        # Then the row falls back to the id rather than inventing a heading
        assert turns[0]["tools"][0]["subject"] is None

    def test_given_one_id_read_twice_when_filled_then_it_is_looked_up_once(
            self, monkeypatch):
        # Given two lookups of the same section, and a counted resolver
        calls = []
        monkeypatch.setattr(
            threads.search, "get_section",
            lambda section_id: calls.append(section_id) or None)
        turns = (self._turn(args={"section_id": "11.2.114"})
                 + self._turn(args={"section_id": "11.2.114"}))

        # When the missing subjects are filled in
        threads.name_missing_subjects(turns)

        # Then the graph was asked once
        assert calls == ["11.2.114"]


class TestLastQuestion:
    def test_given_a_conversation_when_read_then_the_latest_question_wins(self):
        # Given a conversation of two answered turns
        from langchain_core.messages import AIMessage, HumanMessage
        messages = [HumanMessage(content="Prone?"), AIMessage(content="Yes."),
                    HumanMessage(content="Restrained?"), AIMessage(content="No.")]

        # When its last question is found
        found = threads.last_question(messages)

        # Then it is the one a retry would ask again, named by its own id
        assert found == ("Restrained?", messages[2].id)

    def test_given_a_turn_that_failed_when_read_then_the_question_still_stands(
            self):
        # Given a question with no answer under it
        from langchain_core.messages import HumanMessage
        messages = [HumanMessage(content="Prone?")]

        # When its last question is found
        # Then the failure did not take it with it
        assert threads.last_question(messages)[0] == "Prone?"

    def test_given_nothing_asked_when_read_then_there_is_nothing_to_retry(self):
        # Given a conversation with no question in it
        # When its last question is found
        # Then the route has its 404
        assert threads.last_question([]) is None
