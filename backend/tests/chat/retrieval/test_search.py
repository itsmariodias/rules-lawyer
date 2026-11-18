from __future__ import annotations

import pytest

from rules_lawyer.chat.retrieval import search


class TestEscapeLucene:
    def test_given_lucene_syntax_in_a_question_when_escaped_then_it_is_literal(self):
        # Given a question full of characters Lucene reads as syntax
        question = "the target's AC (+2) vs. Fire/Cold"

        # When it is escaped
        escaped = search.escape_lucene(question)

        # Then every one of them is escaped rather than interpreted
        for character in "+()/":
            assert f"\\{character}" in escaped

    def test_given_whitespace_around_a_question_when_escaped_then_it_is_trimmed(self):
        # Given a padded question
        # When it is escaped
        # Then the padding is gone
        assert search.escape_lucene("  prone  ") == "prone"


class TestCitedIds:
    def test_given_a_mix_of_brackets_when_read_then_only_dotted_ids_count(self):
        # Given an answer carrying both kinds of bracket
        text = "Prone [11.2.114] and see [below] and [3] and [4.8.2.3]."

        # When the cited ids are read
        found = search.cited_ids(text)

        # Then only the dotted ids are citations
        assert found == ["11.2.114", "4.8.2.3"]

    def test_given_several_ids_in_one_bracket_when_read_then_each_is_cited(self):
        # Given a claim resting on two sections, cited together, then a
        # semicolon-separated pair and a pair cited one after the other
        text = ("Servants [9.7.6, 9.7.7]; staff [9.7.7;9.7.8]; "
                "or [9.7.6] [9.7.7].")

        # When the cited ids are read
        found = search.cited_ids(text)

        # Then each id counts, in order, however the brackets were written
        assert found == ["9.7.6", "9.7.7", "9.7.7", "9.7.8", "9.7.6", "9.7.7"]

    def test_given_plain_numbers_in_one_bracket_when_read_then_nothing_is_cited(self):
        # Given a bracket of undotted numbers, as in a list of page numbers
        # When the cited ids are read
        # Then it is not taken for a citation
        assert search.cited_ids("See pages [1, 2] and [3.1, 4].") == []


class TestPassage:
    def test_given_a_row_when_read_then_the_label_every_node_carries_is_dropped(self):
        # Given a row as the search query returns it
        row = {"id": "1", "heading": "h", "entity_type": "spell",
               "content": "", "labels": ["Section", "Spell"]}

        # When it is read into a passage
        passage = search.Passage.from_row(row)

        # Then only the label that says something survives
        assert passage.labels == ["Spell"]

    def test_given_a_row_when_read_then_the_offsets_come_with_it(self):
        # Given a row carrying the graph's own view of the passage
        row = {"id": "11.2.114", "heading": "Prone [Condition]",
               "entity_type": "glossary_term", "content": "…",
               "char_start": 100, "char_end": 400, "page_start": 186}

        # When it is read into a passage
        passage = search.Passage.from_row(row)

        # Then the range that resolves the citation is on it
        assert (passage.char_start, passage.char_end) == (100, 400)

    def test_given_a_passage_when_rendered_for_the_ui_then_it_is_a_citation_chip(self):
        # Given a passage
        passage = search.Passage(
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
        # Given a long passage
        passage = search.Passage(
            section_id="11.2.114", heading="Prone [Condition]",
            entity_type="glossary_term", content="x" * 5000, page_start=372)

        # When it is rendered for the model
        rendered = passage.for_model(max_chars=100)

        # Then it opens on the id, and is cut rather than sent whole
        assert rendered.startswith("[11.2.114] Prone [Condition]")
        assert rendered.endswith("…")

    def test_given_a_short_passage_when_rendered_then_nothing_is_cut(self):
        # Given a passage well inside the limit
        passage = search.Passage(section_id="1", heading="A",
                                    entity_type="rule", content="Short.")

        # When it is rendered for the model
        rendered = passage.for_model()

        # Then it ends on the book's own words
        assert rendered.endswith("Short.")

    def test_given_a_passage_with_no_heading_when_rendered_then_it_says_so(self):
        # Given a passage the parser gave no heading
        passage = search.Passage(section_id="1", heading=None,
                                    entity_type=None, content="Text.")

        # When it is rendered for the model
        rendered = passage.for_model()

        # Then the gap is named rather than left blank
        assert "(untitled)" in rendered
        assert "(section," in rendered


class TestSearch:
    def test_given_an_empty_query_when_searched_then_the_index_is_never_reached(self):
        # Given a question of nothing but whitespace
        # When it is searched
        # Then it is answered without a round trip
        assert search.search("   ") == []

    @pytest.mark.neo4j
    def test_given_a_condition_when_searched_then_it_is_found(self, graph):
        # Given a loaded graph
        # When a condition is searched for
        passages = search.search("Prone condition", limit=5)

        # Then the condition itself is among the results, each citable
        assert passages
        assert any(p.heading == "Prone [Condition]" for p in passages)
        assert all(p.section_id for p in passages)

    @pytest.mark.neo4j
    def test_given_a_type_filter_when_searched_then_only_that_type_comes_back(
            self, graph):
        # Given a loaded graph
        # When a search is filtered to spells
        passages = search.search("fireball", limit=5, types=["spell"])

        # Then nothing else came back
        assert passages
        assert {p.entity_type for p in passages} == {"spell"}

    @pytest.mark.neo4j
    def test_given_a_limit_when_searched_then_it_is_respected(self, graph):
        # Given a loaded graph
        # When a search is limited
        passages = search.search("damage", limit=3)

        # Then no more than that many passages come back
        assert len(passages) <= 3


class TestEmbedQuery:
    def test_given_no_key_when_a_query_is_embedded_then_it_is_absent_not_an_error(
            self, settings_env):
        # Given a checkout whose key has been blanked out
        settings_env(GOOGLE_API_KEY="")
        search.embed_query.cache_clear()

        # When a query is embedded
        # Then there is no vector, and no failure either
        assert search.embed_query("prone") is None
        search.embed_query.cache_clear()

    def test_given_a_key_when_a_query_is_embedded_then_it_is_sent_as_a_query(
            self, settings_env, monkeypatch):
        # Given a key, and an embedder that records how it was asked
        settings_env(GOOGLE_API_KEY="not-a-real-key")
        search.embed_query.cache_clear()
        seen = {}

        def record(batch, settings, report=None):
            seen["texts"] = batch
            seen["task_type"] = settings.task_type
            return [[0.0, 1.0]]

        monkeypatch.setattr(search.embeddings, "embed", record)

        # When a query is embedded
        vector = search.embed_query("prone")

        # Then it went as a query, and came back hashable
        assert seen == {"texts": ["prone"], "task_type": "RETRIEVAL_QUERY"}
        assert vector == (0.0, 1.0)
        search.embed_query.cache_clear()

    def test_given_a_repeated_query_when_embedded_then_it_is_not_asked_twice(
            self, settings_env, monkeypatch):
        # Given a key and an embedder that counts its calls
        settings_env(GOOGLE_API_KEY="not-a-real-key")
        search.embed_query.cache_clear()
        calls = []
        monkeypatch.setattr(search.embeddings, "embed",
                            lambda batch, settings, report=None:
                            calls.append(batch) or [[1.0]])

        # When the same query is embedded twice
        search.embed_query("prone")
        search.embed_query("prone")

        # Then the second one never reached the network
        assert len(calls) == 1
        search.embed_query.cache_clear()


class TestVectorSearch:
    def test_given_an_empty_query_when_searched_then_nothing_is_embedded(self):
        # Given a question of nothing but whitespace
        # When it is searched
        # Then it is answered without embedding it or reaching the index
        assert search.vector_search("   ") == []

    def test_given_no_key_when_searched_then_the_arm_is_empty_not_broken(
            self, settings_env):
        # Given a checkout with no key
        settings_env(GOOGLE_API_KEY="")
        search.embed_query.cache_clear()

        # When the dense arm is searched
        # Then it contributes nothing rather than failing the turn
        assert search.vector_search("prone") == []
        search.embed_query.cache_clear()

    @pytest.mark.neo4j
    def test_given_a_paraphrase_when_searched_then_the_book_is_still_found(
            self, graph, embedding_key):
        # Given a loaded graph with vectors on it
        # When a question is asked in words the SRD does not use
        passages = search.vector_search(
            "what happens when a creature is knocked down", limit=10)

        # Then it still lands in the book, citably
        assert passages
        assert all(p.section_id for p in passages)

    @pytest.mark.neo4j
    def test_given_a_type_filter_when_searched_then_only_that_type_comes_back(
            self, graph, embedding_key):
        # Given a loaded graph with vectors on it
        # When the dense arm is filtered to spells
        passages = search.vector_search("a ball of fire", limit=5,
                                           types=["spell"])

        # Then nothing else came back
        assert passages
        assert {p.entity_type for p in passages} == {"spell"}


class TestFuse:
    @staticmethod
    def _passage(section_id: str) -> search.Passage:
        return search.Passage(section_id=section_id, heading=section_id,
                                 entity_type="rule", content="…")

    def test_given_a_passage_both_arms_like_when_fused_then_it_leads(self):
        # Given two rankings that agree on their second choice
        a, b, shared = (self._passage("1"), self._passage("2"),
                        self._passage("3"))
        rankings = {"lexical": [a, shared], "semantic": [b, shared]}

        # When they are fused
        fused = search.fuse(rankings, limit=3)

        # Then the passage both arms returned is first
        assert fused[0].section_id == "3"

    def test_given_a_fused_ranking_when_read_then_it_says_which_arms_found_it(
            self):
        # Given a passage one arm found and a passage both did
        only, both = self._passage("1"), self._passage("2")
        rankings = {"lexical": [only, both], "semantic": [both]}

        # When they are fused
        fused = {p.section_id: p for p in search.fuse(rankings, limit=5)}

        # Then the ranking can be inspected rather than taken on faith
        assert fused["2"].found_by == ["lexical", "semantic"]
        assert fused["1"].found_by == ["lexical"]

    def test_given_a_fused_ranking_when_read_then_the_score_is_the_fused_one(
            self):
        # Given one arm's ranking, whose passage carries the index's own score
        passage = self._passage("1")
        passage.score = 8.4

        # When it is fused
        fused = search.fuse({"lexical": [passage]}, limit=1)

        # Then the score is the reciprocal rank, not what Lucene said
        assert fused[0].score == 1 / (search.RRF_K + 1)

    def test_given_more_results_than_asked_for_when_fused_then_it_is_cut(self):
        # Given two arms returning five passages between them
        rankings = {"lexical": [self._passage(str(i)) for i in range(3)],
                    "semantic": [self._passage(str(i)) for i in range(3, 5)]}

        # When they are fused to three
        fused = search.fuse(rankings, limit=3)

        # Then only three come back
        assert len(fused) == 3

    def test_given_no_results_at_all_when_fused_then_it_is_empty(self):
        # Given two arms that found nothing
        # When they are fused
        # Then the absence survives the fusion
        assert search.fuse({"lexical": [], "semantic": []}, limit=3) == []


@pytest.mark.neo4j
class TestHybridSearch:
    def test_given_no_key_when_searched_then_it_is_the_lexical_arm_alone(
            self, graph, settings_env):
        # Given a loaded graph and no key
        settings_env(GOOGLE_API_KEY="")
        search.embed_query.cache_clear()

        # When the hybrid search runs
        passages = search.hybrid_search("Prone condition", limit=3)

        # Then it answered, and every passage came from the one live arm
        assert passages
        assert all(p.found_by == ["lexical"] for p in passages)
        search.embed_query.cache_clear()

    def test_given_a_question_when_searched_then_it_is_cut_to_the_limit(
            self, graph):
        # Given a loaded graph
        # When a broad question is searched
        passages = search.hybrid_search("damage", limit=3, candidates=8)

        # Then the model reads three passages, not sixteen
        assert len(passages) <= 3

    def test_given_both_arms_when_searched_then_the_fusion_names_them(
            self, graph, embedding_key):
        # Given a loaded graph with vectors on it
        # When a question both arms can answer is searched
        passages = search.hybrid_search("Prone condition", limit=5)

        # Then the result is drawn from both, not from one with a spare step
        assert passages
        assert {arm for p in passages for arm in p.found_by} == {"lexical",
                                                                 "semantic"}


@pytest.mark.neo4j
class TestGetSection:
    def test_given_a_section_when_fetched_then_it_carries_its_offsets(self, graph):
        # Given a loaded graph
        # When a section is fetched
        found = search.get_section("11.2.114")

        # Then it resolves, with the range a citation opens through
        assert found is not None
        passage, _ = found
        assert passage.char_start is not None
        assert passage.char_end > passage.char_start

    def test_given_a_section_when_fetched_then_its_parent_comes_with_it(self, graph):
        # Given a loaded graph
        # When a section is fetched
        _, context = search.get_section("11.2.114")

        # Then the reader can move up from it
        assert context["parent"] is not None
        assert context["parent"]["id"]

    def test_given_a_nested_section_when_fetched_then_its_ancestors_run_from_the_root(
            self, graph):
        # Given a loaded graph
        # When a section three levels deep is fetched
        _, context = search.get_section("11.2.114")

        # Then its ancestors run from the top-level section to its parent
        ids = [ancestor["id"] for ancestor in context["ancestors"]]
        assert ids == ["11", "11.2"]
        assert all(ancestor["heading"] for ancestor in context["ancestors"])
        assert context["ancestors"][-1]["id"] == context["parent"]["id"]

    def test_given_many_subsections_when_fetched_then_they_are_in_book_order(
            self, graph):
        # Given a section with 155 subsections
        # When it is fetched
        _, context = search.get_section("11.2")

        # Then they come back in the order the book prints them
        starts = [child["char_start"] for child in context["children"]]
        assert starts == sorted(starts)
        assert context["children"][0]["id"] == "11.2.1"

    def test_given_a_top_level_section_when_fetched_then_it_has_no_ancestors(
            self, graph):
        # Given a loaded graph
        # When a top-level section is fetched
        _, context = search.get_section("11")

        # Then there is nothing above it
        assert context["ancestors"] == []
        assert context["parent"] is None

    def test_given_a_leaf_section_when_fetched_then_it_has_no_children(self, graph):
        """
        ``collect`` over an unmatched OPTIONAL MATCH yields one all-null map.
        """
        # Given a loaded graph
        # When a section with no subsections is fetched
        _, context = search.get_section("11.2.114")

        # Then the children are an empty list rather than one empty child
        assert context["children"] == []

    def test_given_an_unknown_id_when_fetched_then_it_is_absent_not_empty(
            self, graph):
        # Given a loaded graph
        # When an id that resolves to nothing is fetched
        # Then the absence is answered, so a citation can be dropped
        assert search.get_section("999.999") is None


@pytest.mark.neo4j
class TestQuery:
    def test_given_a_parameter_called_query_when_run_then_it_is_not_the_cypher(
            self, graph):
        """``query`` is also the name of ``Session.run``'s first parameter."""
        # Given a Cypher statement taking a parameter of that name
        # When it is run
        rows = search.query("RETURN $query AS echoed", {"query": "prone"})

        # Then the parameter was passed as data, not as the statement
        assert rows == [{"echoed": "prone"}]
