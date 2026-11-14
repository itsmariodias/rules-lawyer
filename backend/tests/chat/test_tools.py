from __future__ import annotations

import re

import pytest

from dnd_graph_rag.chat import retrieval, tools


class TestSearchSrd:
    def test_given_an_unknown_entity_type_when_called_then_it_never_reaches_the_graph(self):
        # Given a filter naming a type nothing is
        # When the tool is called
        result = tools.search_srd.invoke({"query": "x", "entity_type": "wizardry"})

        # Then the model is told what it may use, rather than getting no results
        assert "Unknown entity_type" in result
        assert "spell" in result

    @pytest.mark.neo4j
    def test_given_only_the_lexical_arm_when_nothing_matches_then_it_says_so(
            self, graph, settings_env):
        # Given a loaded graph, no key, and a question matching no section
        settings_env(GOOGLE_API_KEY="")
        retrieval.embed_query.cache_clear()

        # When the tool is called
        result = tools.search_srd.invoke({"query": "zzzzqqqq"})

        # Then the model is told to try again rather than left with silence
        assert "No SRD sections matched" in result
        retrieval.embed_query.cache_clear()

    @pytest.mark.neo4j
    def test_given_a_nonsense_question_when_searched_then_it_still_guesses(
            self, graph, embedding_key):
        # Given a loaded graph with vectors on it
        # When a question matching no words in the book is searched
        result = tools.search_srd.invoke({"query": "zzzzqqqq"})

        # Then passages come back rather than a refusal
        assert result.startswith("[")

    @pytest.mark.neo4j
    def test_given_a_match_when_called_then_every_result_leads_with_its_id(
            self, graph):
        # Given a loaded graph
        # When the tool is called
        result = tools.search_srd.invoke({"query": "Prone condition"})

        # Then the ids are in front of the passages, where the model will copy them
        assert result.startswith("[")
        assert "[11.2.114]" in result

    @pytest.mark.neo4j
    def test_given_a_known_filter_when_called_then_it_narrows_the_results(
            self, graph):
        # Given a loaded graph
        # When the tool is called filtered to spells
        result = tools.search_srd.invoke({"query": "fire",
                                          "entity_type": "spell"})

        # Then everything returned is a spell
        assert "(spell," in result
        assert "(creature," not in result

    def test_given_the_offered_types_when_read_then_they_are_what_a_reader_asks_about(self):
        # Given the filter the tool offers the model
        # When it is read
        # Then it names the kinds of thing a rules question is about
        assert "spell" in tools.SEARCHABLE_TYPES
        assert "creature" in tools.SEARCHABLE_TYPES
        assert "creature_group" not in tools.SEARCHABLE_TYPES
        assert "front_matter" not in tools.SEARCHABLE_TYPES


@pytest.mark.neo4j
class TestGetSrdSection:
    def test_given_an_unknown_id_when_called_then_the_shape_of_one_is_explained(
            self, graph):
        # Given a loaded graph, and an id no section in it has
        # When the tool is called
        result = tools.get_srd_section.invoke({"section_id": "999.999"})

        # Then the model is told what an id looks like rather than only refused
        assert "No section with id" in result
        assert "11.2.46.1" in result

    def test_given_an_id_when_called_then_the_section_comes_back_with_its_id(
            self, graph):
        # Given a loaded graph
        # When a section is fetched
        result = tools.get_srd_section.invoke({"section_id": "11.2.114"})

        # Then it leads with the id, as a search result does
        assert result.startswith("[11.2.114]")

    def test_given_a_padded_id_when_called_then_it_is_still_found(self, graph):
        # Given an id the model copied with whitespace around it
        # When the tool is called
        result = tools.get_srd_section.invoke({"section_id": "  11.2.114 "})

        # Then the section is found rather than refused on whitespace
        assert result.startswith("[11.2.114]")

    def test_given_a_section_when_called_then_its_neighbours_are_named(self, graph):
        # Given a loaded graph
        # When a section with a parent is fetched
        result = tools.get_srd_section.invoke({"section_id": "11.2.114"})

        # Then the parent is offered by id, ready to be fetched in turn
        assert "Parent: [" in result


class TestDescribe:
    def test_given_a_node_that_is_a_section_when_described_then_it_is_citable(
            self):
        # Given a node the book printed as a heading
        node = {"name": "Prone", "labels": ["Condition", "GlossaryTerm"],
                "section_id": "11.2.114"}

        # When it is described for the model
        # Then it leads with the id, the form a citation takes
        assert tools._describe(node).startswith("[11.2.114] Prone")

    def test_given_a_derived_node_with_nowhere_to_point_when_described_then_it_is_marked_uncitable(
            self):
        # Given a node stage 2 derived, printed in no section
        node = {"uid": "n1", "name": "Bludgeoning",
                "labels": ["DamageType"], "section_id": None, "owner": None}

        # When it is described for the model
        described = tools._describe(node, printed={})

        # Then it is named, and named as something not to cite
        assert "Bludgeoning" in described
        assert "do not cite" in described

    def test_given_a_derived_node_when_described_then_it_points_at_what_to_cite(
            self):
        # Given an ability, and the section the book printed it in
        node = {"uid": "n1", "name": "Roar (3/Day)", "owner": "Sphinx of Valor",
                "labels": ["CreatureAbility"], "section_id": None}
        printed = {"n1": {"section_id": "15.146.3",
                          "heading": "Sphinx of Valor"}}

        # When it is described for the model
        described = tools._describe(node, printed)

        # Then it names an id to use rather than forbidding one
        assert "[15.146.3] Sphinx of Valor — cite that" in described

    def test_given_a_node_pointed_somewhere_when_described_then_its_owner_is_not_repeated(
            self):
        # Given an ability whose owner is the section it was printed in
        node = {"uid": "n1", "name": "Roar (3/Day)", "owner": "Sphinx of Valor",
                "labels": ["CreatureAbility"], "section_id": None}
        printed = {"n1": {"section_id": "15.146.3",
                          "heading": "Sphinx of Valor"}}

        # When it is described for the model
        described = tools._describe(node, printed)

        # Then the creature is named once; twice reads as two facts
        assert described.count("Sphinx of Valor") == 1


class TestRender:
    @staticmethod
    def _node(uid, name, depth, section_id=None, degree=1, summary=None):
        return {"uid": uid, "name": name, "depth": depth, "degree": degree,
                "section_id": section_id, "labels": ["Rule"],
                "entity_type": "rule", "summary": summary, "facts": []}

    def test_given_a_capped_group_when_rendered_then_the_total_is_told(self):
        # Given a neighbourhood whose fan cap cut a group
        data = {
            "root": "a",
            "nodes": [self._node("a", "Prone", 0, "11.2.114", degree=121),
                      self._node("b", "Grease", 1, "7.1.44")],
            "edges": [{"uid": "e", "type": "IMPOSES_CONDITION",
                       "source": "b", "target": "a"}],
            "truncated": [{"uid": "a", "type": "IMPOSES_CONDITION",
                           "direction": "in", "total": 121, "shown": 1}],
        }

        # When it is rendered
        rendered = tools._render(data)

        # Then the model is told what it is not being shown
        assert "121 in the graph, 1 shown" in rendered
        assert "[7.1.44] Grease" in rendered

    def test_given_an_uncapped_group_when_rendered_then_no_total_is_claimed(
            self):
        # Given a neighbourhood the caps cut nothing from
        data = {
            "root": "a",
            "nodes": [self._node("a", "Prone", 0, "11.2.114"),
                      self._node("b", "Grease", 1, "7.1.44")],
            "edges": [{"uid": "e", "type": "REFERENCES_SPELL",
                       "source": "a", "target": "b"}],
            "truncated": [],
        }

        # When it is rendered
        rendered = tools._render(data)

        # Then the group is simply counted, and reads as outgoing
        assert "REFERENCES_SPELL, outgoing — 1:" in rendered

    def test_given_a_second_hop_when_rendered_then_it_is_grouped_by_its_anchor(
            self):
        # Given a neighbourhood two hops deep
        data = {
            "root": "a",
            "nodes": [self._node("a", "Prone", 0, "11.2.114"),
                      self._node("b", "Grease", 1, "7.1.44"),
                      self._node("c", "Wizard", 2, "3.1")],
            "edges": [{"uid": "e1", "type": "IMPOSES_CONDITION",
                       "source": "b", "target": "a"},
                      {"uid": "e2", "type": "ON_SPELL_LIST",
                       "source": "b", "target": "c"}],
            "truncated": [],
        }

        # When it is rendered
        rendered = tools._render(data)

        # Then the far hop hangs off the node it was reached through
        assert "From [7.1.44] Grease" in rendered
        assert rendered.index("Connected to:") < rendered.index("From [7.1.44]")


@pytest.mark.neo4j
class TestExploreSrdGraph:
    def test_given_an_unknown_id_when_called_then_it_never_walks_anything(
            self, graph):
        # Given a loaded graph and an id that resolves to nothing
        result = tools.explore_srd_graph.invoke({"section_id": "999.999"})

        # Then the model is told where ids come from, not given an empty graph
        assert "No section with id" in result
        assert "11.2.46.1" in result

    def test_given_a_condition_when_walked_then_what_imposes_it_is_one_hop_away(
            self, graph):
        # Given a loaded graph, where a condition is its glossary section
        # When the graph around it is walked one hop
        result = tools.explore_srd_graph.invoke({"section_id": "11.2.114"})

        # Then it opens on the section and reaches the abilities imposing it
        assert result.startswith("[11.2.114]")
        assert "Connected to:" in result
        assert "IMPOSES_CONDITION" in result
        assert "DEFINED_IN" not in result

    def test_given_a_shared_passage_when_walked_then_its_terms_are_defined_in_it(
            self, graph):
        # Given the table defining all thirteen damage types
        # When it is walked one hop
        result = tools.explore_srd_graph.invoke({"section_id": "11.2.46.1"})

        # Then the terms are separate nodes pointing at it
        assert "DEFINED_IN" in result
        assert "DamageType" in result

    def test_given_a_condition_when_walked_twice_then_its_imposers_are_reached(
            self, graph):
        # Given a loaded graph
        # When the graph around a condition is walked two hops
        result = tools.explore_srd_graph.invoke({"section_id": "11.2.114",
                                                 "depth": 2})

        # Then the things that impose it are reached, and counted honestly
        assert "IMPOSES_CONDITION" in result
        assert "in the graph," in result

    def test_given_a_walk_when_read_then_every_neighbour_has_an_id_to_cite(
            self, graph):
        # Given a loaded graph
        # When a condition creatures impose is walked to its imposers
        result = tools.explore_srd_graph.invoke({"section_id": "11.2.114",
                                                 "depth": 2})

        # Then the abilities among them carry the section to cite for each
        assert "CreatureAbility" in result
        assert "— cite that" in result


    def test_given_a_wider_fan_when_walked_then_a_sampled_group_is_complete(
            self, graph):
        # Given a loaded graph and a group the default fan samples.  The
        # total is read out of the result rather than written down here: it
        # is a property of the book, and changes whenever the parser learns
        # to read a phrasing it could not read before.
        sampled = tools.explore_srd_graph.invoke({"section_id": "11.2.70",
                                                  "depth": 2})
        cut = re.search(
            r"IMPOSES_CONDITION, incoming — (\d+) in the graph, 8 shown",
            sampled)
        assert cut, sampled
        total = int(cut.group(1))

        # When the same walk is asked for a fan past that total
        whole = tools.explore_srd_graph.invoke({"section_id": "11.2.70",
                                                "depth": 2, "fan": total + 5})

        # Then the group is complete, and no longer reported as cut.  This
        # holds only because the node budget rises with the fan: against the
        # default limit a wider fan widens every group at once and the
        # budget, spent in discovery order, starves the one that was asked
        # for.
        assert f"IMPOSES_CONDITION, incoming — {total}:" in whole

    @pytest.mark.parametrize("section_id, depth", [
        ("11.2.70", 1),    # Frightened: what imposes it is one hop out
        ("11.2.46.1", 2),  # Damage Types: the terms are one hop past it
    ])
    def test_given_a_wider_fan_when_walked_then_the_other_groups_survive_it(
            self, graph, section_id, depth):
        """
        Two hops out from a hub, a wide fan spends the node budget before some
        second-hop groups; the walk is bounded, and query_srd_graph is for
        complete lists.
        """
        # Given a loaded graph and a walk at the default fan
        default = tools.explore_srd_graph.invoke({"section_id": section_id,
                                                  "depth": depth})

        # When the same walk is asked for a much wider fan
        wide = tools.explore_srd_graph.invoke({"section_id": section_id,
                                               "depth": depth, "fan": 30})

        # Then every group it already drew is still there
        for group in re.findall(r"^  (\w+, \w+) —", default, re.M):
            assert group in wide

    def test_given_an_absurd_fan_when_walked_then_it_is_clamped(self, graph):
        # Given a loaded graph
        # When a walk asks for more neighbours than there can be
        result = tools.explore_srd_graph.invoke({"section_id": "11.2.70",
                                                 "fan": 10_000})

        # Then it answers rather than refusing or hanging
        assert result.startswith("[11.2.70]")


class TestQuerySrdGraph:
    def test_given_a_refused_query_when_called_then_it_never_reaches_the_graph(
            self):
        # Given a query calling a procedure outside the allowlist
        # When the tool is called
        result = tools.query_srd_graph.invoke(
            {"cypher_query": "CALL dbms.listConfig() YIELD name RETURN name"})

        # Then the refusal is the answer, without a round trip
        assert "not allowed" in result

    @pytest.mark.neo4j
    def test_given_an_exhaustive_question_when_queried_then_every_row_comes_back(
            self, graph):
        # Given a loaded graph
        # When the question that took sixty tool calls is asked as one query
        result = tools.query_srd_graph.invoke({"cypher_query": """
            MATCH (c:Creature)-[:HAS_ABILITY]->(a)
                  -[:IMPOSES_CONDITION]->(:Condition {name: 'Frightened'})
            RETURN c.id AS id, c.name AS creature, a.name AS ability
        """})

        # Then it answers in rows, complete, each carrying something citable
        assert "rows, all of them" in result
        assert "id | creature | ability" in result
        assert "Pit Fiend" in result

    @pytest.mark.neo4j
    def test_given_a_write_when_called_then_the_model_is_told_plainly(
            self, graph):
        """
        Neo4j's own text is "Unexpected error has occurred. See debug log".
        """
        # Given a loaded graph and a query that would change it
        # When the tool is called
        result = tools.query_srd_graph.invoke(
            {"cypher_query": "MATCH (n:Section) SET n.x = 1 RETURN n.id"})

        # Then it is named as the rule it is, not as an unexpected error
        assert "read-only" in result
        assert "Only MATCH and RETURN" in result

    @pytest.mark.neo4j
    def test_given_broken_cypher_when_called_then_the_error_is_the_result(
            self, graph):
        # Given a loaded graph and a query that will not parse
        # When the tool is called
        result = tools.query_srd_graph.invoke(
            {"cypher_query": "MATCH (n:Section RETURN n"})

        # Then the model is handed the reason and told where to look
        assert "The query failed" in result
        assert "schema" in result


class TestArtifacts:
    @staticmethod
    def _artifact(tool, args: dict) -> dict:
        message = tool.invoke({"type": "tool_call", "id": "1",
                               "name": tool.name, "args": args})
        return message.artifact

    @pytest.mark.neo4j
    def test_given_a_search_when_called_then_the_count_comes_back_with_it(
            self, graph):
        # Given a loaded graph
        # When the search runs
        artifact = self._artifact(tools.search_srd, {"query": "Prone condition"})

        # Then the trace can say what came back, not only that a call happened
        assert artifact["status"] == "ok"
        assert artifact["summary"].endswith("passages")

    @pytest.mark.neo4j
    def test_given_a_section_when_read_then_the_heading_comes_back_with_it(
            self, graph):
        # Given a loaded graph
        # When a section is fetched
        artifact = self._artifact(tools.get_srd_section,
                                  {"section_id": "11.2.114"})

        # Then the trace can name what was read, and still show the id to cite
        assert artifact == {"status": "ok", "summary": "11.2.114",
                            "subject": "Prone [Condition]"}

    @pytest.mark.neo4j
    def test_given_a_walk_when_made_then_the_node_is_named_not_numbered(
            self, graph):
        # Given a loaded graph
        # When the graph around a section is walked
        artifact = self._artifact(tools.explore_srd_graph,
                                  {"section_id": "11.2.114"})

        # Then the row can say what was explored rather than the id it used
        assert artifact["subject"] == "Prone [Condition]"
        assert artifact["summary"].endswith("edges")

    @pytest.mark.neo4j
    def test_given_a_search_when_made_then_no_subject_is_invented_for_it(
            self, graph):
        # Given a loaded graph
        # When a search runs
        artifact = self._artifact(tools.search_srd, {"query": "Prone"})

        # Then the row is left to show the query it was given
        assert "subject" not in artifact

    def test_given_a_refused_query_when_called_then_it_is_not_reported_as_ok(
            self):
        # Given a query calling a procedure outside the allowlist
        # When it is refused
        artifact = self._artifact(
            tools.query_srd_graph,
            {"cypher_query": "CALL dbms.listConfig() YIELD name RETURN name"})

        # Then the refusal reaches the trace
        assert artifact["status"] == "refused"

    @pytest.mark.neo4j
    def test_given_broken_cypher_when_called_then_it_is_reported_as_failed(
            self, graph):
        # Given a loaded graph and a query that will not parse
        # When it fails
        artifact = self._artifact(tools.query_srd_graph,
                                  {"cypher_query": "MATCH (n:Section RETURN n"})

        # Then a broken query does not draw the same row as a working one
        assert artifact["status"] == "failed"

    @pytest.mark.neo4j
    def test_given_a_query_matching_nothing_when_called_then_it_is_empty_not_failed(
            self, graph):
        # Given a loaded graph and a query that matches nothing
        # When it runs
        artifact = self._artifact(
            tools.query_srd_graph,
            {"cypher_query": "MATCH (s:Spell {name: 'nope'}) RETURN s.id"})

        # Then it is distinguished from a failure
        assert artifact == {"status": "empty", "summary": "no rows"}

    @pytest.mark.neo4j
    def test_given_rows_when_returned_then_the_count_is_the_summary(self, graph):
        # Given a loaded graph
        # When a query returns a known number of rows
        artifact = self._artifact(
            tools.query_srd_graph,
            {"cypher_query": "MATCH (s:Spell) RETURN s.id LIMIT 12"})

        # Then the trace can show it without reading the prose result
        assert artifact == {"status": "ok", "summary": "12 rows"}

    @pytest.mark.neo4j
    def test_given_every_tool_when_called_then_none_shows_the_model_its_artifact(
            self, graph):
        # Given a call to each tool
        for tool, args in ((tools.search_srd, {"query": "Prone"}),
                           (tools.get_srd_section, {"section_id": "11.2.114"}),
                           (tools.explore_srd_graph, {"section_id": "11.2.114"}),
                           (tools.query_srd_graph,
                            {"cypher_query": "MATCH (s:Spell) RETURN s.id LIMIT 1"})):
            message = tool.invoke({"type": "tool_call", "id": "1",
                                   "name": tool.name, "args": args})

            # When the content is read
            # Then it is the prose alone
            assert "status" not in message.content
            assert isinstance(message.content, str)

    def test_given_a_tool_when_invoked_plainly_then_it_still_returns_prose(self):
        # Given a call made with arguments rather than a tool call
        result = tools.search_srd.invoke({"query": "x",
                                          "entity_type": "wizardry"})

        # Then the prose is what comes back, not the pair
        assert isinstance(result, str)
        assert "Unknown entity_type" in result


class TestTools:
    def test_given_the_tool_list_when_read_then_it_is_the_four_ways_in(self):
        # Given the list handed to the agent
        # When it is read
        # Then it is two ways into the book and two into the graph
        assert [tool.name for tool in tools.TOOLS] == ["search_srd",
                                                        "get_srd_section",
                                                        "explore_srd_graph",
                                                        "query_srd_graph"]

    def test_given_a_tool_when_described_then_its_arguments_are_documented(self):
        # Given the search tool
        # When its schema is read
        schema = tools.search_srd.args_schema.model_json_schema()

        # Then each argument carries a description
        assert schema["properties"]["query"]["description"]
        assert schema["properties"]["entity_type"]["description"]
