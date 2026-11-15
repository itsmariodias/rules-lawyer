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
