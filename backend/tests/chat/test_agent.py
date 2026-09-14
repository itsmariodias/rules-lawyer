"""
The agent, and the model it runs on.

The tool-calling loop's own reasoning is not a thing a unit test can assert;
what is testable is that a missing key is reported where it can be seen
rather than at settings-load time, and that the prompt still says the things
the rest of the pipeline depends on — citations by id, and the SRD as the
only authority.
"""

from __future__ import annotations

import pytest

from dnd_graph_rag.chat import agent
from dnd_graph_rag.chat.stub import ScriptedModel


class TestModel:
    """The chat model, built from the settings."""

    def test_given_no_api_key_when_built_then_it_is_reported_not_raised_at_import(
            self, settings_env, monkeypatch):
        """
        Raised where it can be reported: the route builds the agent before
        it opens the stream, so a missing key is a 503 rather than a stream
        that stops.
        """
        # Given settings carrying no key — ``.env`` supplies one on this
        # machine, so it is removed from the settings rather than the shell
        settings = settings_env()
        monkeypatch.setattr(settings.chat, "google_api_key", None)

        # When the model is built
        # Then the failure names the setting and what to do about it
        with pytest.raises(agent.NoApiKey, match="GOOGLE_API_KEY"):
            agent.model()

    def test_given_a_key_when_built_then_the_pinned_model_is_used(
            self, settings_env, monkeypatch):
        """
        Pinned rather than a "-latest" alias, which would change the agent's
        behaviour on release without a commit.
        """
        # Given a key in the environment
        monkeypatch.setenv("GOOGLE_API_KEY", "not-a-real-key")
        settings = settings_env()

        # When the model is built
        built = agent.model()

        # Then it is the configured model, at the configured temperature
        assert built.model.endswith(settings.chat.model)
        assert built.temperature == settings.chat.temperature


    def test_given_a_blank_key_when_built_then_it_counts_as_no_key_at_all(
            self, settings_env, monkeypatch):
        """
        ``GOOGLE_API_KEY=`` is how someone turns the key off without deleting
        it.  Without this the empty credential reaches Google and comes back
        as ``API_KEY_INVALID``, when the useful sentence names ``.env``.
        """
        # Given a key blanked out rather than removed
        monkeypatch.setenv("GOOGLE_API_KEY", "   ")
        settings_env()

        # When the model is built
        # Then it fails the way a missing key does
        with pytest.raises(agent.NoApiKey, match="GOOGLE_API_KEY"):
            agent.model()

    def test_given_the_stub_when_built_then_no_key_is_needed(
            self, settings_env, monkeypatch):
        """
        The suites' seam, and only that: nothing turns it on in response to
        a failure, so a real turn without a key still fails.
        """
        # Given the stub asked for, and no key at all
        monkeypatch.setenv("GOOGLE_API_KEY", "")
        settings_env(CHAT_STUB="1")

        # When the model is built
        built = agent.model()

        # Then it is the scripted one
        assert isinstance(built, ScriptedModel)


class TestSystemPrompt:
    """What the agent is told to do."""

    def test_given_the_prompt_when_read_then_it_asks_for_citations_by_id(self):
        """
        ``resolve_citations`` parses these out of the finished answer, so the
        citation chips exist only because the prompt asks for them this way.
        """
        # Given the system prompt
        # When it is read
        # Then it asks for a bracketed section id after each claim
        assert "square brackets" in agent.SYSTEM_PROMPT
        assert "[11.2.46.1]" in agent.SYSTEM_PROMPT

    def test_given_the_prompt_when_read_then_the_srd_is_the_only_authority(self):
        """
        The model's own recollection of D&D is often a different edition;
        "the SRD does not include that" is a correct answer.
        """
        # Given the system prompt
        # When it is read
        # Then it says to search first and not to fill gaps from memory
        assert "Search before you answer" in agent.SYSTEM_PROMPT
        assert "does not include that" in agent.SYSTEM_PROMPT


class TestSystemPromptSchema:
    """The prompt, plus the schema the Cypher tool is written against."""

    def test_given_a_loaded_graph_when_built_then_the_schema_is_appended(
            self, graph):
        """
        In the prompt rather than behind a tool: the model has to know the
        labels at the moment it composes a query.
        """
        # Given a loaded graph
        from dnd_graph_rag.chat import cypher
        cypher.shapes.cache_clear()

        # When the prompt is built
        built = agent.system_prompt()

        # Then it carries what the model needs to write Cypher against
        assert agent.SYSTEM_PROMPT in built
        assert "-[:IMPOSES_CONDITION]->" in built
        cypher.shapes.cache_clear()

    def test_given_an_unreachable_graph_when_built_then_it_costs_the_schema_not_the_turn(
            self, monkeypatch):
        """
        The tools fail with their own message, which is the honest thing for
        a chat whose database is down to say — and much better than a 503 on
        a question the model could have answered.
        """
        # Given a graph that cannot be reached
        from dnd_graph_rag.chat import cypher

        def unreachable() -> str:
            raise OSError("connection refused")

        monkeypatch.setattr(cypher, "schema", unreachable)

        # When the prompt is built
        # Then it is the prompt, without the schema, rather than a failure
        assert agent.system_prompt() == agent.SYSTEM_PROMPT


class TestBuildAgent:
    """The compiled agent, cached per checkpointer."""

    def test_given_the_same_checkpointer_when_built_twice_then_one_graph_is_made(
            self, settings_env, monkeypatch, saver):
        """The server creates one checkpointer, so this builds one per process."""
        # Given a key, so the model can be constructed
        monkeypatch.setenv("GOOGLE_API_KEY", "not-a-real-key")
        settings_env()
        agent.build_agent.cache_clear()

        # When the agent is built twice with the same checkpointer
        first = agent.build_agent(saver)
        second = agent.build_agent(saver)

        # Then the cache handed back what it compiled
        assert first is second
        agent.build_agent.cache_clear()

    def test_given_a_built_agent_when_read_then_it_carries_both_tools(
            self, settings_env, monkeypatch, saver):
        # Given a key and a fresh cache
        monkeypatch.setenv("GOOGLE_API_KEY", "not-a-real-key")
        settings_env()
        agent.build_agent.cache_clear()

        # When an agent is built
        built = agent.build_agent(saver)

        # Then it is a compiled graph holding the conversation's history
        assert built.checkpointer is saver
        agent.build_agent.cache_clear()
