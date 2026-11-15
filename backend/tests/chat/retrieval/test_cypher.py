from __future__ import annotations

import pytest

from rules_lawyer.chat.retrieval import cypher


class TestGuard:
    def test_given_a_plain_match_when_guarded_then_it_passes(self):
        # Given an ordinary query
        # When it is guarded
        # Then nothing objects
        cypher.guard("MATCH (s:Spell) RETURN s.id LIMIT 5")

    def test_given_a_procedure_outside_the_allowlist_when_guarded_then_it_is_refused(
            self):
        """
        ``dbms.listConfig`` is a read, so the read-only transaction would run
        it.
        """
        # Given a query calling a procedure that reads the server's config
        # When it is guarded
        # Then it is refused, and told what it may call instead
        with pytest.raises(cypher.Refused, match="dbms.listConfig"):
            cypher.guard("CALL dbms.listConfig() YIELD name RETURN name")

    def test_given_an_allowed_procedure_when_guarded_then_it_passes(self):
        # Given a query through the full-text index
        # When it is guarded
        # Then the two indexes the graph is searched through are permitted
        cypher.guard("CALL db.index.fulltext.queryNodes('srd_text', 'prone') "
                     "YIELD node RETURN node.id")

    def test_given_a_call_subquery_when_guarded_then_it_is_not_a_procedure(self):
        # Given a query using a scoped subquery
        # When it is guarded
        # Then it is not mistaken for a procedure call
        cypher.guard("MATCH (n:Section) CALL (n) { RETURN n.id AS i } "
                     "RETURN i LIMIT 1")

    def test_given_load_csv_when_guarded_then_it_is_refused(self):
        # Given a query reading from outside the database
        # When it is guarded
        # Then it is refused here rather than left to the server's config
        with pytest.raises(cypher.Refused, match="LOAD CSV"):
            cypher.guard("LOAD CSV FROM 'http://example.com/a.csv' AS row "
                         "RETURN row")

    def test_given_a_spell_named_like_a_write_when_guarded_then_it_passes(self):
        """The SRD has a spell called Create Undead."""
        # Given a query whose string literal contains a write keyword
        # When it is guarded
        # Then the book's own vocabulary is not mistaken for Cypher
        cypher.guard("MATCH (s:Spell) WHERE s.name = 'Create Undead' "
                     "RETURN s.id")

    def test_given_a_procedure_named_in_a_string_when_guarded_then_it_passes(
            self):
        # Given a query that merely mentions a procedure inside a literal
        # When it is guarded
        # Then the literal is cut out before anything is read
        cypher.guard("MATCH (s:Section) WHERE s.content CONTAINS "
                     "'CALL dbms.listConfig' RETURN s.id")


@pytest.mark.neo4j
class TestRead:
    def test_given_a_write_when_read_then_the_database_refuses_it(self, graph):
        """
        The write boundary is the read-only transaction, so it is tested
        against the database.
        """
        # Given a loaded graph and a query that would change it
        # When it is run through the read path
        with pytest.raises(Exception) as refused:
            cypher.read("CREATE (n:ShouldNotExist) RETURN n",
                        timeout=5, max_rows=10)

        # Then the server refused it, and nothing was written
        assert "AccessMode" in str(refused.value)
        assert cypher.read("MATCH (n:ShouldNotExist) RETURN count(n) AS c",
                           timeout=5, max_rows=10)[0] == [{"c": 0}]

    def test_given_more_rows_than_the_cap_when_read_then_it_says_there_are_more(
            self, graph):
        # Given a loaded graph and a query matching thousands of nodes
        # When it is read with a small cap
        rows, truncated = cypher.read("MATCH (s:Section) RETURN s.id AS id",
                                      timeout=10, max_rows=5)

        # Then the cap is respected and the cut is reported rather than hidden
        assert len(rows) == 5
        assert truncated is True

    def test_given_fewer_rows_than_the_cap_when_read_then_it_is_complete(
            self, graph):
        # Given a loaded graph and a query matching a handful
        # When it is read
        rows, truncated = cypher.read(
            "MATCH (c:GlossaryTerm:Condition) RETURN c.name AS name",
            timeout=10, max_rows=100)

        # Then the answer is the whole answer, and says so
        assert len(rows) == 15
        assert truncated is False


class TestForm:
    def test_given_a_multi_label_node_when_formed_then_section_is_dropped(self):
        # Given the labels of a spell node
        # When they are formed for the schema
        # Then only the label that identifies it survives
        assert cypher._form(["Section", "Spell"]) == ":Spell"

    def test_given_a_node_that_is_only_a_section_when_formed_then_it_stays(self):
        # Given a node carrying nothing more specific
        # When its labels are formed
        # Then the one label there is remains, rather than an empty match
        assert cypher._form(["Section"]) == ":Section"


@pytest.mark.neo4j
class TestShapes:
    def test_given_a_loaded_graph_when_read_then_the_edges_are_described(
            self, graph):
        # Given a loaded graph
        cypher.shapes.cache_clear()

        # When the shapes are derived
        described = cypher.shapes()

        # Then each relationship says what it joins, in Cypher's own notation
        assert "(:Creature)-[:HAS_ABILITY]->(:CreatureAbility)" in described
        assert "-[:IMPOSES_CONDITION]->(:GlossaryTerm:Condition)" in described
        cypher.shapes.cache_clear()

    def test_given_the_schema_when_read_then_it_carries_what_no_query_can_say(
            self, graph):
        # Given a loaded graph
        cypher.shapes.cache_clear()

        # When the whole schema is assembled
        described = cypher.schema()

        # Then the facts introspection cannot state are in it too
        assert "multi-label" in described
        assert "only citable identifier" in described
        cypher.shapes.cache_clear()


class TestRender:
    def test_given_rows_when_rendered_then_the_columns_are_the_ones_asked_for(
            self):
        # Given two rows as the driver returns them
        rows = [{"id": "15.122.1", "name": "Pit Fiend", "dc": 21},
                {"id": "15.127.1", "name": "Quasit", "dc": 10}]

        # When they are rendered
        rendered = cypher.render(rows, truncated=False)

        # Then the header names the columns the query asked for
        assert "id | name | dc" in rendered
        assert "15.122.1 | Pit Fiend | 21" in rendered

    def test_given_a_complete_result_when_rendered_then_it_says_it_is_complete(
            self):
        # Given every row there is
        # When it is rendered
        rendered = cypher.render([{"a": 1}], truncated=False)

        # Then the count is stated as the whole of it
        assert "1 rows, all of them" in rendered

    def test_given_a_cut_result_when_rendered_then_it_says_there_are_more(self):
        # Given rows the cap cut
        # When they are rendered
        rendered = cypher.render([{"a": 1}], truncated=True)

        # Then an answer is not built on 50 rows that were silently the first
        # 50 of 300
        assert "there are more" in rendered

    def test_given_a_long_value_when_rendered_then_it_is_cut(self):
        # Given a row carrying a whole passage
        rows = [{"content": "x" * 5000}]

        # When it is rendered
        rendered = cypher.render(rows, truncated=False)

        # Then the cell is cut rather than sent whole
        assert len(rendered) < cypher.CELL_CHARS + 100
        assert rendered.endswith("…")

    def test_given_a_description_length_cell_when_rendered_then_it_survives(self):
        """At 200 characters the cap cut 22% of ability descriptions."""
        # Given a cell the size of a real ability description
        text = ("_Wisdom Saving Throw:_ DC 18, each enemy in a 30-foot "
                "Emanation. _Failure:_ 28 (8d6) Psychic damage, and the "
                "target has the Frightened and Incapacitated conditions "
                "until the start of the rakshasa's next turn. ") * 2

        # When it is rendered
        rendered = cypher.render([{"description": text}], truncated=False)

        # Then the mechanics the answer needs are all there
        assert "…" not in rendered

    def test_given_more_rows_than_fit_when_rendered_then_whole_rows_are_dropped(
            self):
        # Given far more text than the output budget allows
        rows = [{"id": str(i), "text": "x" * 500} for i in range(200)]

        # When it is rendered
        rendered = cypher.render(rows, truncated=False)

        # Then it says how many matched and how many it could show
        assert len(rendered) < cypher.TOTAL_CHARS + cypher.CELL_CHARS + 200
        assert "200 rows matched, showing the first" in rendered
        assert "did not fit" in rendered

    def test_given_one_enormous_row_when_rendered_then_it_is_still_shown(self):
        # Given a single row larger than the whole budget
        rows = [{"text": "x" * 500}]

        # When it is rendered
        rendered = cypher.render(rows, truncated=False)

        # Then the answer is not an empty table
        assert "1 rows, all of them" in rendered
        assert "x" in rendered

    def test_given_a_list_value_when_rendered_then_it_reads_as_one_cell(self):
        # Given a row carrying one of the mapper's parallel arrays
        rows = [{"damage_types": ["Fire", "Cold"]}]

        # When it is rendered
        rendered = cypher.render(rows, truncated=False)

        # Then it stays on its row rather than breaking the table
        assert "Fire, Cold" in rendered

    def test_given_a_null_when_rendered_then_the_cell_is_empty_not_none(self):
        # Given a row whose optional property is absent
        # When it is rendered
        rendered = cypher.render([{"dc": None}], truncated=False)

        # Then the cell is blank
        assert rendered.endswith("dc\n")

    def test_given_no_rows_when_rendered_then_it_says_so_and_suggests_why(self):
        # Given a query that matched nothing
        # When it is rendered
        rendered = cypher.render([], truncated=False)

        # Then the model is told where to look rather than given a blank
        assert "matched nothing" in rendered
        assert "relationship directions" in rendered
