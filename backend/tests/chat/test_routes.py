"""
Stage 3 over HTTP: the chat stream, its threads, and what a citation opens.

The routes hold no state — the checkpointer and the store are opened by the
app's lifespan and reached through ``request.app.state`` — so the client here
runs the lifespan, with the conversation files pointed at a temporary
directory.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from dnd_graph_rag.api import app


def events_of(response) -> list[dict]:
    """The SSE body, back into the dicts ``service`` yielded."""
    return [json.loads(line[len("data: "):])
            for line in response.text.splitlines()
            if line.startswith("data: ")]


@pytest.fixture
def client(settings_env, tmp_path):
    """
    A client whose conversations live in a temporary directory.

    Only ``chat/`` is temporary — ``/source`` reads the real markdown and
    anchors, so ``source/`` and ``output/`` are linked through to the
    checkout rather than copied.  ``CHAT_STUB=1`` so a turn runs the scripted
    model rather than reaching Gemini: the agent loop, the tools and the
    citations are the live ones, and every event a real turn emits arrives.
    """
    from dnd_graph_rag.chat import source
    from dnd_graph_rag.chat.agent import build_agent
    from dnd_graph_rag.config import get_settings

    real = get_settings().data_dir
    for name in ("source", "output"):
        (tmp_path / name).symlink_to(real / name)
    settings_env(DND_GRAPH_RAG_DATA=str(tmp_path), CHAT_STUB="1")
    build_agent.cache_clear()
    source.markdown.cache_clear()
    source.anchors.cache_clear()

    with TestClient(app) as running:
        yield running

    source.markdown.cache_clear()
    source.anchors.cache_clear()
    build_agent.cache_clear()


class TestChat:
    """One turn, streamed as server-sent events."""

    def test_given_a_message_when_posted_then_the_stream_opens_with_a_thread_id(
            self, client, graph):
        """Minted here when the browser sends none, and reported so it can
        keep using it."""
        # Given a first message with no thread
        response = client.post("/chat", json={"message": "Prone condition"})

        # When the stream is read
        events = events_of(response)

        # Then it opens by naming the conversation it started
        assert response.status_code == 200
        assert events[0]["type"] == "start"
        assert events[0]["thread_id"]

    def test_given_a_turn_when_streamed_then_it_is_not_buffered_by_a_proxy(
            self, client, graph):
        """Without these a reverse proxy delivers the answer in one piece,
        which defeats the point."""
        # Given a turn
        response = client.post("/chat", json={"message": "Prone condition"})

        # When the headers are read
        # Then it is an event stream that asks not to be buffered
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"

    def test_given_a_turn_when_streamed_then_every_event_type_arrives(
            self, client, graph):
        # Given a turn
        response = client.post("/chat", json={"message": "Prone condition"})

        # When the events are read
        kinds = [event["type"] for event in events_of(response)]

        # Then the whole contract the browser renders is there
        for expected in ("start", "tool_start", "tool_end", "token",
                         "usage", "citations", "done"):
            assert expected in kinds

    def test_given_no_api_key_when_posted_then_the_turn_is_refused_outright(
            self, client, settings_env, monkeypatch):
        """
        The model is required, and a missing key is the one failure knowable
        before the response is committed — so it is an HTTP error rather than
        an event buried in a stream that had already opened as a turn.
        """
        # Given a server with the key blanked out and no stub
        from dnd_graph_rag.chat.agent import build_agent

        monkeypatch.setenv("GOOGLE_API_KEY", "")
        settings_env(CHAT_STUB="0")
        build_agent.cache_clear()

        # When a turn is posted
        response = client.post("/chat", json={"message": "Prone condition"})

        # Then it is refused, in words naming what to fix
        assert response.status_code == 503
        assert "GOOGLE_API_KEY" in response.json()["detail"]
        build_agent.cache_clear()

    def test_given_a_thread_id_when_posted_then_the_turn_joins_that_conversation(
            self, client, graph):
        # Given a conversation the browser already holds an id for
        client.post("/chat", json={"message": "Prone condition",
                                   "thread_id": "held"})

        # When a second turn is posted under the same id
        response = client.post("/chat", json={"message": "Restrained condition",
                                              "thread_id": "held"})

        # Then the stream reports the id it was given rather than a new one
        assert events_of(response)[0]["thread_id"] == "held"

    def test_given_an_empty_message_when_posted_then_it_is_refused(self, client):
        # Given a message with nothing in it
        # When it is posted
        response = client.post("/chat", json={"message": ""})

        # Then it is rejected before a turn is started
        assert response.status_code == 422


class TestChatThreads:
    """Stored conversations, pinned first and newest first within that."""

    def test_given_no_conversations_when_listed_then_the_list_is_empty(self, client):
        # Given a fresh store
        # When the threads are listed
        # Then it answers, with nothing in it
        assert client.get("/chat/threads").json() == {"threads": []}

    def test_given_two_conversations_when_listed_then_the_newest_leads(
            self, client, graph):
        # Given two conversations
        client.post("/chat", json={"message": "Prone condition",
                                   "thread_id": "older"})
        client.post("/chat", json={"message": "Restrained condition",
                                   "thread_id": "newer"})

        # When they are listed
        listed = client.get("/chat/threads").json()["threads"]

        # Then the most recent is first, titled by its opening question
        assert [t["thread_id"] for t in listed] == ["newer", "older"]
        assert listed[0]["title"] == "Restrained condition"

    def test_given_a_new_conversation_when_listed_then_its_summary_is_the_title(
            self, client, graph, monkeypatch):
        """
        Written beside the opening turn and stored before its stream ends,
        which is when the browser refreshes the list.  Only the opening turn
        asks for one: a follow-up does not retitle the conversation.
        """
        # Given a model that titles every question it is asked about
        from dnd_graph_rag.chat import titles

        asked: list[str] = []

        async def summarise(question: str) -> str:
            asked.append(question)
            return "Prone condition effects"

        monkeypatch.setattr(titles, "summarise", summarise)

        # When a conversation is opened and then followed up
        start = events_of(client.post(
            "/chat", json={"message": "What exactly does Prone do?"}))[0]
        client.post("/chat", json={"message": "And Restrained?",
                                   "thread_id": start["thread_id"]})

        # Then it is listed by its summary, written once
        listed, = client.get("/chat/threads").json()["threads"]
        assert listed["title"] == "Prone condition effects"
        assert asked == ["What exactly does Prone do?"]


class TestChatThread:
    """One conversation's turns, for reopening it in the UI."""

    def test_given_a_stored_conversation_when_fetched_then_its_turns_come_back(
            self, client, graph):
        # Given a conversation with one turn in it
        client.post("/chat", json={"message": "Prone condition",
                                   "thread_id": "kept"})

        # When it is fetched
        body = client.get("/chat/threads/kept").json()

        # Then the question and its answer are both there
        assert body["thread_id"] == "kept"
        assert [m["role"] for m in body["messages"]] == ["user", "assistant"]

    def test_given_a_stored_conversation_when_fetched_then_its_cost_matches_the_live_one(
            self, client, graph):
        """Both read the stored messages, so reopening shows what was shown."""
        # Given a turn, and what it reported as it streamed
        live = next(e for e in events_of(client.post(
            "/chat", json={"message": "Prone condition", "thread_id": "kept"}))
            if e["type"] == "usage")

        # When the conversation is fetched
        answer = client.get("/chat/threads/kept").json()["messages"][-1]

        # Then the answer carries the same count
        del live["type"]
        assert answer["usage"] == live

    def test_given_a_stored_conversation_when_fetched_then_its_turns_are_dated(
            self, client, graph):
        """
        Taken from the checkpoint that stored each message, which is the one
        thing that survives a reload and a restart.
        """
        # Given an answered conversation
        client.post("/chat", json={"message": "Prone condition",
                                   "thread_id": "dated"})

        # When it is reopened
        messages = client.get("/chat/threads/dated").json()["messages"]

        # Then every turn carries when it happened, in order
        stamps = [m["at"] for m in messages]
        assert all(stamps)
        assert stamps == sorted(stamps)

    def test_given_a_reopened_conversation_when_fetched_then_the_lookups_survive(
            self, client, graph):
        """
        The retrieval used to be dropped on the way back, so a conversation
        reopened from the list showed its answers with nothing under them and
        the trace read as something that had never happened.

        This is the test that has to go through the real checkpointer: the
        status and summary ride on the tool result as an artifact, and an
        artifact that does not survive being written to SQLite and read back
        would fail here and nowhere else.
        """
        # Given a conversation whose answer came from a search
        client.post("/chat", json={"message": "Prone condition",
                                   "thread_id": "kept"})

        # When it is reopened
        body = client.get("/chat/threads/kept").json()
        answer = body["messages"][1]

        # Then the lookup is under the answer, finished, with its outcome
        assert len(answer["tools"]) == 1
        [lookup] = answer["tools"]
        assert lookup["name"] == "search_srd"
        assert lookup["args"]["query"] == "Prone condition"
        assert lookup["done"] is True
        assert lookup["status"] == "ok"
        assert lookup["summary"].endswith("passages")
    def test_given_an_id_nobody_used_when_fetched_then_it_is_a_not_found(
            self, client):
        # Given an id nothing was stored under
        # When it is fetched
        # Then the UI can tell an empty conversation from a missing one
        assert client.get("/chat/threads/never-used").status_code == 404


class TestPinThread:
    """Pinning, which decides where a conversation sits in the list."""

    def test_given_a_conversation_when_pinned_then_it_sorts_above_the_rest(
            self, client, graph):
        # Given two conversations, the older one pinned
        client.post("/chat", json={"message": "Prone condition",
                                   "thread_id": "older"})
        client.post("/chat", json={"message": "Restrained condition",
                                   "thread_id": "newer"})

        # When the older is pinned
        response = client.put("/chat/threads/older/pin", json={"pinned": True})

        # Then it moves to the top of the listing
        assert response.status_code == 204
        listed = client.get("/chat/threads").json()["threads"]
        assert [t["thread_id"] for t in listed] == ["older", "newer"]

    def test_given_a_pinned_conversation_when_unpinned_then_the_order_returns(
            self, client, graph):
        # Given a pinned conversation
        client.post("/chat", json={"message": "Prone condition",
                                   "thread_id": "older"})
        client.post("/chat", json={"message": "Restrained condition",
                                   "thread_id": "newer"})
        client.put("/chat/threads/older/pin", json={"pinned": True})

        # When it is unpinned
        client.put("/chat/threads/older/pin", json={"pinned": False})

        # Then newest-first applies again
        listed = client.get("/chat/threads").json()["threads"]
        assert [t["pinned"] for t in listed] == [False, False]

    def test_given_a_thread_that_does_not_exist_when_pinned_then_it_is_a_not_found(
            self, client):
        """A pin on a thread that does not exist is a row nothing would read."""
        # Given an id nothing was stored under
        # When it is pinned
        response = client.put("/chat/threads/never-used/pin",
                              json={"pinned": True})

        # Then it is refused
        assert response.status_code == 404


class TestChatLookup:
    """What one lookup in a conversation returned."""

    def test_given_a_stored_lookup_when_fetched_then_its_result_comes_back(
            self, client, graph):
        """
        Its own request rather than part of the conversation: one turn of a
        real question stores a hundred kilobytes of table, almost none of
        which anyone opens.
        """
        # Given an answered conversation
        client.post("/chat", json={"message": "Prone condition",
                                   "thread_id": "kept"})
        [lookup] = [c for m in client.get("/chat/threads/kept").json()["messages"]
                    for c in m.get("tools", [])]

        # When its result is fetched
        body = client.get(f"/chat/threads/kept/lookups/{lookup['id']}").json()

        # Then it is the prose the model was given, whole
        assert body["name"] == "search_srd"
        assert body["content"].startswith("[")
        assert body["truncated"] is False

    def test_given_an_unknown_lookup_when_fetched_then_it_is_a_404(
            self, client, graph):
        # Given an answered conversation
        client.post("/chat", json={"message": "Prone condition",
                                   "thread_id": "kept"})

        # When a call that was never made is fetched
        # Then it is absent rather than an empty panel
        assert client.get("/chat/threads/kept/lookups/nope").status_code == 404

    def test_given_an_unknown_thread_when_fetched_then_it_is_a_404(self, client):
        # Given no such conversation
        # When a lookup in it is fetched
        # Then it is absent
        assert client.get("/chat/threads/ghost/lookups/x").status_code == 404


class TestForgetThread:
    """Deleting one conversation: its turns, its tool calls and its pin."""

    def test_given_a_conversation_when_deleted_then_it_leaves_the_listing(
            self, client, graph):
        # Given a stored conversation
        client.post("/chat", json={"message": "Prone condition",
                                   "thread_id": "doomed"})

        # When it is deleted
        response = client.delete("/chat/threads/doomed")

        # Then nothing of it is offered any more
        assert response.status_code == 204
        assert client.get("/chat/threads").json() == {"threads": []}
        assert client.get("/chat/threads/doomed").status_code == 404

    def test_given_an_id_nobody_used_when_deleted_then_it_is_a_not_found(
            self, client):
        """So the UI can tell a delete from a no-op."""
        # Given an id nothing was stored under
        # When it is deleted
        # Then the absence is reported
        assert client.delete("/chat/threads/never-used").status_code == 404


class TestRetryTurn:
    """Asking the last question again, in place of the answer it got."""

    def test_given_an_answered_turn_when_retried_then_it_is_replaced(
            self, client, graph):
        """
        The property the whole feature rests on.  Re-sending the text would
        append, and a conversation holding the same question twice is what a
        reader would find the next time they opened it.

        Through the real checkpointer, because the rewind is a branch in it
        and nothing else would catch a fork that left the old turn standing.
        """
        # Given a conversation of two answered turns
        client.post("/chat", json={"message": "Prone condition",
                                   "thread_id": "again"})
        client.post("/chat", json={"message": "Restrained condition",
                                   "thread_id": "again"})

        # When the last of them is retried
        response = client.post("/chat/threads/again/retry")

        # Then it was answered afresh, and the conversation is still two turns
        assert response.status_code == 200
        events = events_of(response)
        assert events[0] == {"type": "start", "thread_id": "again"}
        assert any(event["type"] == "token" for event in events)
        messages = client.get("/chat/threads/again").json()["messages"]
        assert [m["content"] for m in messages if m["role"] == "user"] == [
            "Prone condition", "Restrained condition"]
        assert len(messages) == 4

    def test_given_the_only_turn_of_a_thread_when_retried_then_it_is_alone(
            self, client, graph):
        """
        The first question has no checkpoint before it to branch from, so it
        rewinds by clearing the thread.  The id has to survive that: it is
        what the browser is holding and what a pin would be keyed on.
        """
        # Given a conversation of one turn
        client.post("/chat", json={"message": "Prone condition",
                                   "thread_id": "first"})

        # When it is retried
        response = client.post("/chat/threads/first/retry")

        # Then the thread still holds exactly that one question
        assert response.status_code == 200
        messages = client.get("/chat/threads/first").json()["messages"]
        assert [m["content"] for m in messages if m["role"] == "user"] == [
            "Prone condition"]
        listed = client.get("/chat/threads").json()["threads"]
        assert [(t["thread_id"], t["messages"]) for t in listed] == [
            ("first", 1)]

    def test_given_a_retried_turn_when_reopened_then_the_new_lookups_are_under_it(
            self, client, graph):
        """A retry re-runs the retrieval, so the trace under the answer has
        to be the one that produced it."""
        # Given a retried conversation
        client.post("/chat", json={"message": "Prone condition",
                                   "thread_id": "traced"})
        client.post("/chat/threads/traced/retry")

        # When it is reopened
        answer = client.get("/chat/threads/traced").json()["messages"][1]

        # Then the answer carries one finished lookup, not two turns' worth
        assert len(answer["tools"]) == 1
        assert answer["tools"][0]["done"] is True

    def test_given_an_id_nobody_used_when_retried_then_it_is_a_not_found(
            self, client):
        """Raised before the response is committed, so a 404 never arrives
        inside a stream that has already announced itself as a turn."""
        # Given an id nothing was stored under
        # When it is retried
        response = client.post("/chat/threads/never-used/retry")

        # Then there was nothing to ask again
        assert response.status_code == 404
        assert "never-used" in response.json()["detail"]


class TestSource:
    """The SRD text behind a citation."""

    def test_given_a_citation_when_fetched_then_the_book_and_its_geometry_arrive(
            self, client, graph):
        # Given a cited section
        # When its source is fetched
        body = client.get("/source/11.2.114").json()

        # Then the text, the highlight and the page rectangles all come back
        assert body["heading"] == "Prone [Condition]"
        assert body["text"]
        assert body["highlight"]["start"] == 0
        assert body["pages"] == [186]

    def test_given_context_when_fetched_then_the_slice_widens(self, client, graph):
        # Given the same citation
        tight = client.get("/source/11.2.114").json()

        # When it is fetched with context
        wide = client.get("/source/11.2.114", params={"context": 400}).json()

        # Then more of the book comes with it, and the highlight still marks it
        assert len(wide["text"]) > len(tight["text"])
        assert wide["text"][wide["highlight"]["start"]:
                            wide["highlight"]["end"]] == tight["text"]

    def test_given_an_unknown_id_when_fetched_then_it_is_a_not_found(
            self, client, graph):
        # Given an id no section has
        # When its source is fetched
        # Then it is reported missing
        assert client.get("/source/999.999").status_code == 404


class TestNeighbourhood:
    """The graph around one node."""

    def test_given_a_citation_when_asked_then_the_nodes_and_edges_come_back(
            self, client, graph):
        # Given a cited section
        # When its neighbourhood is asked for
        body = client.get("/neighbourhood",
                          params={"section": "11.2.114"}).json()

        # Then the seed is the root, drawn with what surrounds it
        assert body["root"]
        assert body["nodes"] and body["edges"]

    def test_given_a_drawn_node_when_asked_then_it_expands_by_its_own_id(
            self, client, graph):
        """
        A citation names a section, but the interesting neighbours are not
        all sections — so a drawn node is addressed by the uid it came with.
        """
        # Given a node from an earlier answer
        first = client.get("/neighbourhood",
                           params={"section": "11.2.114"}).json()
        node = first["nodes"][1]["uid"]

        # When that node is expanded
        response = client.get("/neighbourhood", params={"node": node})

        # Then it opens like any other seed
        assert response.status_code == 200
        assert response.json()["root"] == node

    def test_given_neither_a_section_nor_a_node_when_asked_then_it_is_refused(
            self, client):
        # Given no seed at all
        # When the neighbourhood is asked for
        response = client.get("/neighbourhood")

        # Then the requirement is stated rather than guessed at
        assert response.status_code == 400
        assert "exactly one" in response.json()["detail"]

    def test_given_both_a_section_and_a_node_when_asked_then_it_is_refused(
            self, client):
        # Given two ways of naming the seed at once
        # When the neighbourhood is asked for
        response = client.get("/neighbourhood",
                              params={"section": "11.2.114", "node": "x"})

        # Then it is refused
        assert response.status_code == 400

    def test_given_a_fan_of_zero_when_asked_then_it_is_raised_to_one(
            self, client, graph):
        """A fan of zero would return a seed and nothing at all."""
        # Given caps below what draws anything
        # When the neighbourhood is asked for
        body = client.get("/neighbourhood",
                          params={"section": "11.2.114", "fan": 0,
                                  "limit": 0}).json()

        # Then the seed is drawn with at least one neighbour
        assert len(body["nodes"]) >= 1

    def test_given_an_unknown_section_when_asked_then_it_is_a_not_found(
            self, client, graph):
        # Given an id no section has
        # When its neighbourhood is asked for
        # Then it is reported missing rather than drawn empty
        assert client.get("/neighbourhood",
                          params={"section": "999.999"}).status_code == 404
