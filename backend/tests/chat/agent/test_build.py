from __future__ import annotations

import pytest

from rules_lawyer.chat.agent import build
from tests.fakes import FakeChatModel


class TestSystemPrompt:
    def test_given_the_prompt_when_read_then_it_asks_for_citations_by_id(self):
        # Given the system prompt
        # When it is read
        # Then it asks for a bracketed section id after each claim
        assert "square brackets" in build.SYSTEM_PROMPT
        assert "[11.2.46.1]" in build.SYSTEM_PROMPT

    def test_given_the_prompt_when_read_then_the_srd_is_the_only_authority(self):
        # Given the system prompt
        # When it is read
        # Then it says to search first and not to fill gaps from memory
        assert "Search before you answer" in build.SYSTEM_PROMPT
        assert "does not include that" in build.SYSTEM_PROMPT


class TestSystemPromptSchema:
    @pytest.mark.neo4j
    def test_given_a_loaded_graph_when_built_then_the_schema_is_appended(
            self, graph):
        # Given a loaded graph
        from rules_lawyer.chat.retrieval import cypher
        cypher.shapes.cache_clear()

        # When the prompt is built
        built = build.system_prompt()

        # Then it carries what the model needs to write Cypher against
        assert build.SYSTEM_PROMPT in built
        assert "-[:IMPOSES_CONDITION]->" in built
        cypher.shapes.cache_clear()

    def test_given_an_unreachable_graph_when_built_then_it_costs_the_schema_not_the_turn(
            self, monkeypatch):
        # Given a graph that cannot be reached
        from rules_lawyer.chat.retrieval import cypher

        def unreachable() -> str:
            raise OSError("connection refused")

        monkeypatch.setattr(cypher, "schema", unreachable)

        # When the prompt is built
        # Then it is the prompt, without the schema, rather than a failure
        assert build.system_prompt() == build.SYSTEM_PROMPT


class TestBuildAgent:
    def test_given_a_built_agent_when_read_then_it_holds_the_conversation(self, saver):
        # Given the fake model
        # When an agent is built
        built = build.build_agent(FakeChatModel(), saver)

        # Then it is a compiled graph holding the conversation's history
        assert built.checkpointer is saver

    def test_given_the_graph_comes_up_after_a_build_when_rebuilt_then_the_schema_is_added(
            self, monkeypatch, saver):
        """Regression: an agent built while Neo4j was down kept no schema."""
        # Given an agent built while the graph was unreachable
        from rules_lawyer.chat.retrieval import cypher

        asked: list[str] = []

        def unreachable() -> str:
            asked.append("down")
            raise OSError("connection refused")

        monkeypatch.setattr(cypher, "schema", unreachable)
        build.build_agent(FakeChatModel(), saver)

        # When the graph becomes reachable and the agent is built again
        monkeypatch.setattr(cypher, "schema", lambda: asked.append("up") or "SCHEMA")
        build.build_agent(FakeChatModel(), saver)

        # Then the schema was asked for again rather than the old prompt kept
        assert asked == ["down", "up"]



LONG_RESULT = "[11.2.46.1] Prone (glossary_term, p.188)\n" + "word " * 200


def _thread_of_two_turns() -> list:
    """A first turn with a long lookup, then a second question mid-lookup."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    return [
        HumanMessage("What does Prone do?", id="q1"),
        AIMessage("", id="call1", tool_calls=[
            {"name": "search_srd", "args": {"query": "Prone"}, "id": "t1"}]),
        ToolMessage(LONG_RESULT, tool_call_id="t1", id="r1"),
        AIMessage("Prone creatures crawl [11.2.46.1].", id="a1"),
        HumanMessage("And Grappled?", id="q2"),
        AIMessage("", id="call2", tool_calls=[
            {"name": "search_srd", "args": {"query": "Grappled"}, "id": "t2"}]),
        ToolMessage(LONG_RESULT, tool_call_id="t2", id="r2"),
    ]


class TestWithEarlierLookupsCut:
    def test_given_two_turns_when_cut_then_only_the_earlier_result_is_shortened(self):
        # Given a finished turn with a long lookup, and a second turn mid-lookup
        messages = _thread_of_two_turns()

        # When the conversation is cut for the model
        sent = build.with_earlier_lookups_cut(messages)

        # Then every message is still there, in order
        assert [m.id for m in sent] == [m.id for m in messages]
        # and the earlier result keeps its header, cut and marked
        earlier = sent[2].content
        assert earlier.startswith("[11.2.46.1] Prone (glossary_term, p.188)")
        assert len(earlier) < build.EARLIER_LOOKUP_CHARS + 50
        assert earlier.endswith("(cut: an earlier turn's lookup)")
        # while the current turn's result is whole
        assert sent[6].content == LONG_RESULT

    def test_given_a_cut_when_made_then_the_stored_message_is_untouched(self):
        # Given the thread's stored messages
        messages = _thread_of_two_turns()

        # When the conversation is cut for the model
        build.with_earlier_lookups_cut(messages)

        # Then the originals still hold the whole result
        assert messages[2].content == LONG_RESULT

    def test_given_a_short_earlier_result_when_cut_then_it_is_sent_whole(self):
        # Given an earlier result already under the limit
        messages = _thread_of_two_turns()
        messages[2] = messages[2].model_copy(update={"content": "[1.2] Short"})

        # When the conversation is cut for the model
        sent = build.with_earlier_lookups_cut(messages)

        # Then it is sent as it is, with no marker
        assert sent[2].content == "[1.2] Short"

    def test_given_no_question_when_cut_then_the_messages_are_unchanged(self):
        # Given no human message at all
        # When cut
        # Then nothing changes
        assert build.with_earlier_lookups_cut([]) == []


class TestCutEarlierLookups:
    def _request(self):
        from langchain.agents.middleware import ModelRequest

        return ModelRequest(model=FakeChatModel(), messages=_thread_of_two_turns())

    def test_given_a_sync_call_when_wrapped_then_the_model_gets_the_cut_turns(self):
        # Given a model call over two turns
        sent: list = []

        # When the middleware wraps it
        build.CutEarlierLookups().wrap_model_call(
            self._request(), lambda request: sent.extend(request.messages))

        # Then the model is handed the earlier result cut
        assert sent[2].content.endswith("(cut: an earlier turn's lookup)")

    @pytest.mark.asyncio
    async def test_given_an_async_call_when_wrapped_then_the_model_gets_the_cut_turns(self):
        # Given a model call over two turns, as the streaming agent makes it
        sent: list = []

        async def handler(request):
            sent.extend(request.messages)

        # When the middleware wraps it
        await build.CutEarlierLookups().awrap_model_call(self._request(), handler)

        # Then the model is handed the earlier result cut
        assert sent[2].content.endswith("(cut: an earlier turn's lookup)")

    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_a_follow_up_when_answered_then_the_store_keeps_the_lookup_whole(
            self, graph, saver):
        """The model is sent less; the checkpointer still stores everything."""
        from langchain_core.messages import ToolMessage

        # Given an agent that has answered one question with a long lookup
        agent = build.build_agent(FakeChatModel(), saver)
        config = {"configurable": {"thread_id": "follow-up"}}
        await agent.ainvoke({"messages": [("user", "Prone condition")]}, config)

        # When a second question is asked
        state = await agent.ainvoke(
            {"messages": [("user", "Grappled condition")]}, config)

        # Then the first lookup is stored whole, not as the model was sent it
        first = next(m for m in state["messages"] if isinstance(m, ToolMessage))
        assert len(first.content) > build.EARLIER_LOOKUP_CHARS
        assert "(cut:" not in first.content


class TestToolCallLimit:
    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_a_model_that_keeps_searching_when_over_budget_then_it_answers(
            self, graph, saver, settings_env):
        from uuid import uuid4

        from langchain_core.messages import AIMessage, ToolMessage
        from langchain_core.outputs import ChatGeneration, ChatResult

        class Researcher(FakeChatModel):
            """Searches until a call is refused, then answers."""

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                refused = any(isinstance(m, ToolMessage) and m.status == "error"
                              for m in messages)
                reply = (AIMessage("Answered from what I found.") if refused
                         else AIMessage("", tool_calls=[{
                             "name": "search_srd", "args": {"query": "Prone"},
                             "id": uuid4().hex}]))
                return ChatResult(generations=[ChatGeneration(message=reply)])

        # Given a budget of two lookups and a model that never stops looking
        settings_env(CHAT_MAX_TOOL_CALLS="2")
        agent = build.build_agent(Researcher(), saver)

        # When it is asked a question
        state = await agent.ainvoke(
            {"messages": [("user", "Prone condition")]},
            {"configurable": {"thread_id": "budget"}})

        # Then two lookups ran, the third was refused unrun, and it answered
        results = [m for m in state["messages"] if isinstance(m, ToolMessage)]
        assert [m.status for m in results] == ["success", "success", "error"]
        assert state["messages"][-1].content == "Answered from what I found."
