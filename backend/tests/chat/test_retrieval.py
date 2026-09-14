"""
The graph, read: full-text search and one section by id.

The escaping is pure; the two queries need a loaded graph and skip without
one.  Both return a ``Passage``, which is what carries a citation back to the
markdown and to the printed page.
"""

from __future__ import annotations

import pytest

from dnd_graph_rag.chat import retrieval


class TestEscapeLucene:
    """A rules question, matched as words rather than as syntax."""

    def test_given_lucene_syntax_in_a_question_when_escaped_then_it_is_literal(self):
        """A rules question is natural language: "the target's AC (+2)"."""
        # Given a question full of characters Lucene reads as syntax
        question = "the target's AC (+2) vs. Fire/Cold"

        # When it is escaped
        escaped = retrieval.escape_lucene(question)

        # Then every one of them is escaped rather than interpreted
        for character in "+()/":
            assert f"\\{character}" in escaped

    def test_given_whitespace_around_a_question_when_escaped_then_it_is_trimmed(self):
        # Given a padded question
        # When it is escaped
        # Then the padding is gone
        assert retrieval.escape_lucene("  prone  ") == "prone"


class TestPassage:
    """A citable piece of the book."""

    def test_given_a_row_when_read_then_the_label_every_node_carries_is_dropped(self):
        """``:Section`` is on 2368 nodes and carries no information."""
        # Given a row as the search query returns it
        row = {"id": "1", "heading": "h", "entity_type": "spell",
               "content": "", "labels": ["Section", "Spell"]}

        # When it is read into a passage
        passage = retrieval.Passage.from_row(row)

        # Then only the label that says something survives
        assert passage.labels == ["Spell"]

    def test_given_a_row_when_read_then_the_offsets_come_with_it(self):
        # Given a row carrying the graph's own view of the passage
        row = {"id": "11.2.114", "heading": "Prone [Condition]",
               "entity_type": "glossary_term", "content": "…",
               "char_start": 100, "char_end": 400, "page_start": 186}

        # When it is read into a passage
        passage = retrieval.Passage.from_row(row)

        # Then the range that resolves the citation is on it
        assert (passage.char_start, passage.char_end) == (100, 400)

    def test_given_a_passage_when_rendered_for_the_ui_then_it_is_a_citation_chip(self):
        # Given a passage
        passage = retrieval.Passage(
            section_id="11.2.114", heading="Prone [Condition]",
            entity_type="glossary_term", content="…", page_start=186,
            labels=["Condition"])

        # When it is rendered as a citation
        citation = passage.as_citation()

        # Then it is the subset the UI needs to draw and open it
        assert citation == {"section_id": "11.2.114",
                            "heading": "Prone [Condition]",
                            "entity_type": "glossary_term", "page": 186,
                            "labels": ["Condition"]}

    def test_given_a_passage_when_rendered_for_the_model_then_the_id_leads(self):
        """The prompt asks for citations by id, and the model copies what it
        can see."""
        # Given a long passage
        passage = retrieval.Passage(
            section_id="11.2.114", heading="Prone [Condition]",
            entity_type="glossary_term", content="x" * 5000, page_start=372)

        # When it is rendered for the model
        rendered = passage.for_model(max_chars=100)

        # Then it opens on the id, and is cut rather than sent whole
        assert rendered.startswith("[11.2.114] Prone [Condition]")
        assert rendered.endswith("…")

    def test_given_a_short_passage_when_rendered_then_nothing_is_cut(self):
        # Given a passage well inside the limit
        passage = retrieval.Passage(section_id="1", heading="A",
                                    entity_type="rule", content="Short.")

        # When it is rendered for the model
        rendered = passage.for_model()

        # Then it ends on the book's own words
        assert rendered.endswith("Short.")

    def test_given_a_passage_with_no_heading_when_rendered_then_it_says_so(self):
        # Given a passage the parser gave no heading
        passage = retrieval.Passage(section_id="1", heading=None,
                                    entity_type=None, content="Text.")

        # When it is rendered for the model
        rendered = passage.for_model()

        # Then the gap is named rather than left blank
        assert "(untitled)" in rendered
        assert "(section," in rendered


class TestSearch:
    """Lexical search over every section's heading and prose."""

    def test_given_an_empty_query_when_searched_then_the_index_is_never_reached(self):
        # Given a question of nothing but whitespace
        # When it is searched
        # Then it is answered without a round trip
        assert retrieval.search("   ") == []

    def test_given_a_condition_when_searched_then_it_is_found(self, graph):
        # Given a loaded graph
        # When a condition is searched for
        passages = retrieval.search("Prone condition", limit=5)

        # Then the condition itself is among the results, each citable
        assert passages
        assert any(p.heading == "Prone [Condition]" for p in passages)
        assert all(p.section_id for p in passages)

    def test_given_a_type_filter_when_searched_then_only_that_type_comes_back(
            self, graph):
        """
        Filtering happens after the index rather than before it: the index is
        the only thing that can rank, so the limit is raised and the surplus
        discarded.
        """
        # Given a loaded graph
        # When a search is filtered to spells
        passages = retrieval.search("fireball", limit=5, types=["spell"])

        # Then nothing else came back
        assert passages
        assert {p.entity_type for p in passages} == {"spell"}

    def test_given_a_limit_when_searched_then_it_is_respected(self, graph):
        # Given a loaded graph
        # When a search is limited
        passages = retrieval.search("damage", limit=3)

        # Then no more than that many passages come back
        assert len(passages) <= 3


class TestGetSection:
    """One section, plus the two hops that let a reader move around it."""

    def test_given_a_section_when_fetched_then_it_carries_its_offsets(self, graph):
        # Given a loaded graph
        # When a section is fetched
        found = retrieval.get_section("11.2.114")

        # Then it resolves, with the range a citation opens through
        assert found is not None
        passage, _ = found
        assert passage.char_start is not None
        assert passage.char_end > passage.char_start

    def test_given_a_section_when_fetched_then_its_parent_comes_with_it(self, graph):
        # Given a loaded graph
        # When a section is fetched
        _, context = retrieval.get_section("11.2.114")

        # Then the reader can move up from it
        assert context["parent"] is not None
        assert context["parent"]["id"]

    def test_given_a_leaf_section_when_fetched_then_it_has_no_children(self, graph):
        """``collect`` over a missing OPTIONAL MATCH yields one null-filled map."""
        # Given a loaded graph
        # When a section with no subsections is fetched
        _, context = retrieval.get_section("11.2.114")

        # Then the children are an empty list rather than one empty child
        assert context["children"] == []

    def test_given_an_unknown_id_when_fetched_then_it_is_absent_not_empty(
            self, graph):
        # Given a loaded graph
        # When an id that resolves to nothing is fetched
        # Then the absence is answered, so a citation can be dropped
        assert retrieval.get_section("999.999") is None


class TestQuery:
    """The one call every read goes through."""

    def test_given_a_parameter_called_query_when_run_then_it_is_not_the_cypher(
            self, graph):
        """
        Parameters go to Neo4j as a dict, never as keywords: one of them is
        called ``query``, which is also ``Session.run``'s first argument.
        """
        # Given a Cypher statement taking a parameter of that name
        # When it is run
        rows = retrieval.query("RETURN $query AS echoed", {"query": "prone"})

        # Then the parameter was passed as data, not as the statement
        assert rows == [{"echoed": "prone"}]
