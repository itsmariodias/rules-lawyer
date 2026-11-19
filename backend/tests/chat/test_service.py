from __future__ import annotations

import pytest

from rules_lawyer.chat import service as chat_service
from rules_lawyer.chat.agent import titles
from rules_lawyer.chat.service import ChatService
from tests.fakes import FakeChatService


@pytest.fixture
def service(saver, store) -> ChatService:
    """A service over in-memory storage, answered by the fake model."""
    return FakeChatService(saver, store)


async def answer(service: ChatService, thread_id: str,
                 question: str = "Prone condition") -> None:
    """Run one turn to its end."""
    async for _ in await service.ask(question, thread_id):
        pass


async def stored(saver, thread_id: str, *messages) -> dict:
    """Write one checkpoint holding ``messages``, as a finished turn leaves it."""
    from langgraph.checkpoint.base import empty_checkpoint

    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"messages": list(messages)}
    # A checkpointer stores only the channels whose versions it is given.
    checkpoint["channel_versions"] = {"messages": 1}
    return await saver.aput({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
                            checkpoint, {}, {"messages": 1})


def answered(question: str, answer: str = "Prone creatures crawl."):
    """A question and its answer, with no section cited."""
    from langchain_core.messages import AIMessage, HumanMessage

    return HumanMessage(content=question), AIMessage(content=answer)


class TestModel:
    def test_given_a_key_when_read_then_it_is_the_configured_model(
            self, saver, store, settings_env, monkeypatch):
        # Given a key in the environment
        monkeypatch.setenv("GOOGLE_API_KEY", "not-a-real-key")
        settings = settings_env()

        # When a service's model is read twice
        chats = ChatService(saver, store)
        built = chats.model

        # Then it is the configured model, built once
        assert built.model.endswith(settings.chat.model)
        assert chats.model is built


class TestAsk:
    @pytest.mark.asyncio
    async def test_given_no_key_when_asked_then_it_fails_before_any_stream(
            self, saver, store, settings_env):
        # Given no key to build the model with
        from rules_lawyer.chat.agent.model import ModelUnavailable

        settings_env(GOOGLE_API_KEY="", CHAT_PROVIDER="google")

        # When a question is asked
        # Then the request fails, rather than a stream that errors later
        with pytest.raises(ModelUnavailable, match="GOOGLE_API_KEY"):
            await ChatService(saver, store).ask("Prone condition")

    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_no_thread_when_asked_then_the_stream_names_a_new_one(
            self, graph, service):
        # Given a question with no thread
        # When it is asked
        events = [event async for event in await service.ask("Prone condition")]

        # Then the stream opens by naming the thread it started, and ends there
        assert events[0]["type"] == "start"
        assert events[0]["thread_id"]
        assert events[-1] == {"type": "done", "thread_id": events[0]["thread_id"]}

    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_an_opening_turn_when_it_ends_then_its_title_is_stored(
            self, graph, service, store, monkeypatch):
        # Given a model that titles the question
        async def summarise(question, model):
            return "Prone condition effects"

        monkeypatch.setattr(titles, "summarise", summarise)

        # When a thread's first turn ends
        await answer(service, "titled")

        # Then the title is stored for the list
        assert await titles.titled(store) == {"titled": "Prone condition effects"}

    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_an_opening_turn_when_titled_then_the_title_is_sent_before_done(
            self, graph, service, monkeypatch):
        # Given a model that titles the question
        async def summarise(question, model):
            return "Prone condition effects"

        monkeypatch.setattr(titles, "summarise", summarise)

        # When a thread's first turn runs
        events = [event async for event in await service.ask("Prone condition", "titled")]

        # Then the title is one event, sent while the turn is still open
        kinds = [event["type"] for event in events]
        assert kinds.count("title") == 1
        assert kinds.index("title") < kinds.index("done") == len(kinds) - 1
        assert events[kinds.index("title")] == {
            "type": "title", "thread_id": "titled", "title": "Prone condition effects"}

    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_no_title_from_the_model_when_asked_then_the_cut_question_is_sent(
            self, graph, service, store, monkeypatch):
        # Given a model that fails to title the question
        async def summarise(question, model):
            return None

        monkeypatch.setattr(titles, "summarise", summarise)

        # When a thread's first turn runs
        events = [event async for event in await service.ask(
            "What exactly happens to a creature that has the Prone condition?", "cut")]

        # Then the question, cut as the list cuts it, is sent before done
        kinds = [event["type"] for event in events]
        assert kinds.index("title") < kinds.index("done")
        assert events[kinds.index("title")]["title"] == (
            "What exactly happens to a creature that has the Prone…")

        # And nothing is stored, so the list keeps falling back to the question
        assert await titles.titled(store) == {}

    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_a_later_turn_when_asked_then_no_title_is_sent(
            self, graph, service, monkeypatch):
        # Given a thread already answered once, and a model that titles anything
        await answer(service, "later")

        async def summarise(question, model):
            return "Restrained condition effects"

        monkeypatch.setattr(titles, "summarise", summarise)

        # When a second question is asked in it
        events = [event async for event in await service.ask("Restrained condition", "later")]

        # Then the thread keeps its title
        assert "title" not in [event["type"] for event in events]


class TestRetry:
    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_a_later_turn_when_retried_then_it_branches_before_it(
            self, graph, service):
        # Given a conversation of two answered turns
        await answer(service, "again", "Prone condition")
        await answer(service, "again", "Restrained condition")

        # When the last of them is asked again
        events = [event async for event in await service.retry("again")]

        # Then the question was asked once, still after the first
        assert events[0] == {"type": "start", "thread_id": "again"}
        turns = await service.history("again")
        assert [t["content"] for t in turns if t["role"] == "user"] == [
            "Prone condition", "Restrained condition"]

    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_the_only_turn_when_retried_then_it_branches_before_it(
            self, graph, service):
        """
        The graph checkpoints once before the input, so the first turn has an
        empty state to branch from.
        """
        # Given a conversation of one answered turn
        await answer(service, "first", "Prone condition")

        # When it is asked again
        async for _ in await service.retry("first"):
            pass

        # Then the conversation is still that one question, under its own id
        turns = await service.history("first")
        assert [t["content"] for t in turns if t["role"] == "user"] == [
            "Prone condition"]
        assert [t["thread_id"] for t in await service.list_threads()] == ["first"]

    @pytest.mark.asyncio
    async def test_given_a_thread_nobody_used_when_retried_then_there_is_nothing(
            self, service):
        # Given an id nothing was stored under
        # When it is retried
        # Then there is no question to ask again
        assert await service.retry("never-used") is None


class TestHistory:
    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_a_stored_thread_when_read_then_the_turns_come_back(
            self, graph, service):
        # Given a thread with one turn in it
        await answer(service, "kept", "Prone condition")

        # When it is read back
        turns = await service.history("kept")

        # Then the question opens it, with its answer's citations resolved
        assert turns[0]["role"] == "user"
        assert turns[0]["content"] == "Prone condition"
        # and dated, from the checkpoint that stored it
        assert turns[0]["at"]
        assert turns[1]["role"] == "assistant"
        assert turns[1]["citations"]

    @pytest.mark.asyncio
    async def test_given_no_api_key_when_read_then_the_stored_turns_still_come_back(
            self, saver, store, settings_env):
        # Given a stored conversation, and no key to build a model with
        settings_env(GOOGLE_API_KEY="")
        await stored(saver, "kept", *answered("Prone?"))
        reader = ChatService(saver, store)

        # When it is read back
        turns = await reader.history("kept")

        # Then reading what was stored needed no model
        assert [turn["content"] for turn in turns] == ["Prone?", "Prone creatures crawl."]

    @pytest.mark.asyncio
    async def test_given_the_graph_down_when_read_then_the_turns_come_back_unlinked(
            self, saver, store, monkeypatch):
        # Given a stored answer citing a section, and no graph to resolve it
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        from neo4j.exceptions import ServiceUnavailable

        from rules_lawyer.chat.retrieval import search

        def unreachable(section_id):
            raise ServiceUnavailable("Couldn't connect to localhost:7687")

        monkeypatch.setattr(search, "get_section", unreachable)
        await stored(saver, "kept", HumanMessage(content="Prone?"),
                     AIMessage(content="", tool_calls=[{
                         "name": "get_srd_section",
                         "args": {"section_id": "11.2.114"}, "id": "call-1"}]),
                     ToolMessage(content="Prone", tool_call_id="call-1",
                                 name="get_srd_section"),
                     AIMessage(content="Prone creatures crawl [11.2.114]."))
        reader = ChatService(saver, store)

        # When it is read back
        turns = await reader.history("kept")

        # Then the conversation opens, its citation and lookup left unresolved
        assert [turn["content"] for turn in turns] == [
            "Prone?", "Prone creatures crawl [11.2.114]."]
        assert turns[1]["citations"] == []
        assert turns[1]["tools"][0]["subject"] is None

    @pytest.mark.asyncio
    async def test_given_a_thread_nobody_used_when_read_then_it_is_empty(
            self, service):
        # Given an id nothing was stored under
        # When it is read back
        # Then the route can answer 404 from the emptiness
        assert await service.history("never-used") == []


class TestLookup:
    @pytest.mark.asyncio
    async def test_given_a_step_still_running_when_looked_up_then_a_finished_result_is_found(
            self, saver, service):
        # Given a lookup whose result is written while its step is unfinished
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        config = await stored(saver, "busy", HumanMessage(content="Prone?"), AIMessage(
            content="", tool_calls=[{"name": "search_srd", "args": {}, "id": "call-1"}]))
        await saver.aput_writes(config, [("messages", [ToolMessage(
            content="the result", tool_call_id="call-1", name="search_srd")])], "task-1")

        # When it is looked up
        found = await service.lookup("busy", "call-1")

        # Then it is there before the step is checkpointed
        assert found["content"] == "the result"

    @pytest.mark.asyncio
    async def test_given_no_api_key_when_looked_up_then_the_stored_result_still_comes_back(
            self, saver, store, settings_env):
        # Given a stored result, and no key to build a model with
        from langchain_core.messages import ToolMessage
        settings_env(GOOGLE_API_KEY="")
        await stored(saver, "kept", ToolMessage(content="kept result", tool_call_id="call-1",
                                                name="search_srd"))
        reader = ChatService(saver, store)

        # When it is looked up
        found = await reader.lookup("kept", "call-1")

        # Then reading what was stored needed no model
        assert found["content"] == "kept result"


class TestListThreads:
    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_two_conversations_when_listed_then_the_newest_leads(
            self, graph, service):
        # Given two conversations, one after the other
        await answer(service, "older", "Prone condition")
        await answer(service, "newer", "Restrained condition")

        # When they are listed
        listed = await service.list_threads()

        # Then the most recent is first
        assert [t["thread_id"] for t in listed] == ["newer", "older"]

    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_a_pinned_conversation_when_listed_then_it_sorts_above(
            self, graph, service):
        # Given two conversations with the older one pinned
        await answer(service, "older", "Prone condition")
        await answer(service, "newer", "Restrained condition")
        await service.set_pinned("older", True)

        # When they are listed
        listed = await service.list_threads()

        # Then the pin outranks the ordering
        assert [t["thread_id"] for t in listed] == ["older", "newer"]
        assert [t["pinned"] for t in listed] == [True, False]

    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_a_conversation_when_listed_then_it_is_titled_by_its_question(
            self, graph, service):
        # Given a conversation opened with a long question
        question = "What happens to a creature that " + "really " * 20 + "falls?"
        await answer(service, "titled", question)

        # When it is listed
        listed, = await service.list_threads()

        # Then the title is the question, cut at a word
        assert listed["title"].startswith("What happens to a creature")
        assert listed["title"].endswith("…")
        assert len(listed["title"]) <= 61

    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_a_stored_title_when_listed_then_it_names_the_conversation(
            self, graph, service, store):
        # Given two conversations, only one of them titled
        await answer(service, "titled", "What exactly does the Prone condition do?")
        await answer(service, "untitled", "Restrained condition")
        await titles.remember(store, "titled", "Prone condition effects")

        # When they are listed
        listed = {t["thread_id"]: t["title"] for t in await service.list_threads()}

        # Then the title is used where there is one, and the question elsewhere
        assert listed == {"titled": "Prone condition effects",
                          "untitled": "Restrained condition"}

    @pytest.mark.asyncio
    async def test_given_pins_beyond_the_scan_when_listed_then_every_pin_is_there(
            self, saver, service, monkeypatch):
        # Given two pinned conversations and a scan that reaches only one
        monkeypatch.setattr(chat_service, "CHECKPOINTS_PER_THREAD", 1)
        await stored(saver, "first", *answered("Prone?"))
        await stored(saver, "second", *answered("Restrained?"))
        await service.set_pinned("first", True)
        await service.set_pinned("second", True)

        # When one thread is asked for
        listed = await service.list_threads(limit=1)

        # Then both pins are listed anyway: the limit is for the rest
        assert sorted(t["thread_id"] for t in listed) == ["first", "second"]
        assert all(t["pinned"] for t in listed)

    @pytest.mark.asyncio
    async def test_given_many_pins_when_listed_then_every_one_is_pinned(
            self, saver, service):
        """``BaseStore.asearch`` returns ten results by default."""
        # Given more pinned conversations than a default page holds
        for n in range(11):
            await stored(saver, f"t{n}", *answered(f"Question {n}?"))
            await service.set_pinned(f"t{n}", True)

        # When they are listed
        listed = await service.list_threads()

        # Then none has lost its pin
        assert sum(t["pinned"] for t in listed) == 11


class TestSetPinned:
    @pytest.mark.asyncio
    async def test_given_a_pin_when_removed_then_the_row_is_deleted(
            self, saver, store, service):
        # Given a pinned conversation
        await stored(saver, "kept", *answered("Prone?"))
        await service.set_pinned("kept", True)

        # When it is unpinned
        await service.set_pinned("kept", False)

        # Then the row is gone, rather than holding a false
        assert await store.asearch(chat_service.PINS) == []

    @pytest.mark.asyncio
    async def test_given_no_such_thread_when_pinned_then_nothing_is_stored(
            self, store, service):
        # Given an id nothing was stored under
        # When it is pinned
        pinned = await service.set_pinned("never-used", True)

        # Then the route can answer 404, and no pin was written
        assert pinned is False
        assert await store.asearch(chat_service.PINS) == []


class TestForget:
    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_a_conversation_when_deleted_then_nothing_of_it_remains(
            self, graph, service):
        # Given a stored conversation
        await answer(service, "doomed")
        assert [t["thread_id"] for t in await service.list_threads()] == ["doomed"]

        # When it is deleted
        deleted = await service.forget("doomed")

        # Then it is gone from the listing and from the history
        assert deleted is True
        assert await service.list_threads() == []
        assert await service.history("doomed") == []

    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_a_pinned_conversation_when_deleted_then_the_pin_goes_too(
            self, graph, service, store):
        # Given a pinned conversation
        await answer(service, "doomed")
        await service.set_pinned("doomed", True)

        # When it is deleted
        await service.forget("doomed")

        # Then its pin went with it
        assert await store.asearch(chat_service.PINS) == []

    @pytest.mark.neo4j
    @pytest.mark.asyncio
    async def test_given_a_titled_conversation_when_deleted_then_the_title_goes_too(
            self, graph, service, store):
        # Given a titled conversation
        await answer(service, "doomed")
        await titles.remember(store, "doomed", "Prone condition effects")

        # When it is deleted
        await service.forget("doomed")

        # Then its title went with it
        assert await titles.titled(store) == {}

    @pytest.mark.asyncio
    async def test_given_a_thread_nobody_used_when_deleted_then_it_says_so(
            self, service):
        # Given an id nothing was stored under
        # When it is deleted
        # Then the route can answer 404
        assert await service.forget("never-used") is False
