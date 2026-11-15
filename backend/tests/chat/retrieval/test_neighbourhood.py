from __future__ import annotations

import pytest

from rules_lawyer.chat.retrieval import neighbourhood, search


def row(anchor, uid, type_="REFERENCES_SPELL", outgoing=True, total=1,
        edge=None) -> dict:
    """One ``_NEIGHBOURS`` row."""
    return {"anchor": anchor, "uid": uid, "type": type_, "outgoing": outgoing,
            "total": total, "edge": edge or f"{anchor}->{uid}",
            "labels": ["Section", "Spell"], "entity_type": "spell",
            "name": uid, "section_id": uid, "page": 1, "degree": 3}


def seed(uid="root") -> dict:
    return {"uid": uid, "labels": ["Section"], "entity_type": "rule",
            "name": "Root", "section_id": uid, "page": 1, "degree": 9}


class TestSummarise:
    def test_given_the_books_own_emphasis_when_summarised_then_it_is_stripped(self):
        # Given content carrying markdown emphasis mid-sentence
        content = "While Prone, **_Restricted Movement._** You crawl."

        # When it is summarised
        # Then the words survive and the markers do not
        assert neighbourhood._summarise(content) == \
            "While Prone, Restricted Movement. You crawl."

    def test_given_a_section_that_is_only_a_table_when_summarised_then_it_says_nothing(self):
        """The Mysterious Deck's content is a hundred-row table."""
        # Given a section whose content is a table
        content = ("**1d100** **1d100**\n\n| **(13-Card** | **Card** |\n"
                   "|---|---|\n| 01–05 | Balance |\n| 06–10 | Comet |")

        # When it is summarised
        # Then silence lets the facts take the space instead
        assert neighbourhood._summarise(content) is None

    def test_given_a_heading_orphaned_by_its_table_when_summarised_then_it_goes_too(self):
        # Given a table's column heading printed above it as its own paragraph
        content = ("**1d100**\n\n| a | b |\n|---|---|\n\n"
                   "Each card is described below.")

        # When it is summarised
        # Then the stranded heading was cut with the rows it labelled
        assert neighbourhood._summarise(content) == \
            "Each card is described below."

    def test_given_a_short_line_with_no_table_under_it_when_summarised_then_it_stays(self):
        """
        Stat blocks open with short lines like "Medium Undead, Neutral evil".
        """
        # Given a short opening line followed by more prose
        content = "_Medium Undead, Neutral evil_\n\n**AC** 20 **Initiative** +3"

        # When it is summarised
        # Then the line survived
        assert neighbourhood._summarise(content).startswith(
            "Medium Undead, Neutral evil AC 20")

    def test_given_a_long_passage_when_summarised_then_it_is_cut_at_a_word(self):
        # Given more prose than a card can hold
        # When it is summarised
        summary = neighbourhood._summarise("word " * 200)

        # Then it is cut to the card's size, at a word boundary
        assert len(summary) <= neighbourhood.SUMMARY_CHARS + 2
        assert summary.endswith("word…")

    def test_given_no_content_at_all_when_summarised_then_there_is_no_summary(self):
        # Given a node with no prose
        # When it is summarised
        # Then nothing is claimed
        assert neighbourhood._summarise(None) is None


class TestFacts:
    def test_given_a_table_row_when_read_then_it_says_what_it_does_carry(self):
        # Given the properties of a node that has no description
        pairs = [["name", "Dagger"], ["damage_dice", "1d4"],
                 ["page_start", 71], ["damage_type", "Piercing"],
                 ["kind", "weapon"], ["cost_gp", 2.0]]

        # When the facts are read
        facts = neighbourhood._facts(pairs)

        # Then keys and structure are dropped and substance is kept
        assert [f["name"] for f in facts] == ["damage dice", "damage type"]
        assert facts[0]["value"] == "1d4"

    def test_given_parallel_resource_arrays_when_read_then_they_are_recombined(self):
        # Given the two lists as the graph holds them
        pairs = [["resource_names", ["Rages", "Rage Damage"]],
                 ["resource_values", ["3", "+2"]]]

        # When the facts are read
        facts = neighbourhood._facts(pairs)

        # Then they read as the table row they came from
        assert facts == [{"name": "resources",
                          "value": "Rages 3, Rage Damage +2"}]

    def test_given_a_long_value_when_read_then_it_is_a_line_not_a_paragraph(self):
        # Given a property longer than a card's line
        pairs = [["starting_equipment", "Choose " + "x " * 200]]

        # When the facts are read
        facts = neighbourhood._facts(pairs)

        # Then it is cut to a line, at a word
        assert len(facts[0]["value"]) <= neighbourhood.FACT_CHARS + 1
        assert facts[0]["value"].endswith("…")

    def test_given_no_properties_at_all_when_read_then_there_are_no_facts(self):
        # Given a node with nothing on it
        # When the facts are read
        # Then the list is empty
        assert neighbourhood._facts(None) == []


class TestAssemble:
    def test_given_a_seed_when_assembled_then_it_is_the_only_node_at_depth_zero(self):
        # Given one hop of neighbours
        # When the graph is assembled
        graph = neighbourhood.assemble(seed(), [[row("root", "a")]], limit=10)

        # Then the seed is the centre and its neighbours are one hop out
        assert {n["uid"]: n["depth"] for n in graph["nodes"]} == {"root": 0,
                                                                  "a": 1}
        assert graph["root"] == "root"

    def test_given_a_node_reached_twice_when_assembled_then_it_keeps_the_shorter_path(self):
        # Given a second hop that reaches back to the seed
        rounds = [[row("root", "a")], [row("a", "root", edge="back")]]

        # When the graph is assembled
        graph = neighbourhood.assemble(seed(), rounds, limit=10)

        # Then the seed keeps depth zero, and both edges are drawn once each
        assert next(n["depth"] for n in graph["nodes"]
                    if n["uid"] == "root") == 0
        assert len(graph["nodes"]) == 2
        assert len(graph["edges"]) == 2

    def test_given_an_incoming_edge_when_assembled_then_its_direction_survives(self):
        # Given a row matched from the far end
        # When the graph is assembled
        graph = neighbourhood.assemble(
            seed(), [[row("root", "a", outgoing=False)]], limit=10)

        # Then the arrow still points the way the database drew it
        edge, = graph["edges"]
        assert (edge["source"], edge["target"]) == ("a", "root")

    def test_given_nodes_when_assembled_then_the_label_every_node_carries_is_dropped(self):
        # Given nodes labelled `:Section`
        # When the graph is assembled
        graph = neighbourhood.assemble(seed(), [[row("root", "a")]], limit=10)

        # Then only the labels that say which node this is survive
        assert [n["labels"] for n in graph["nodes"]] == [[], ["Spell"]]

    def test_given_more_nodes_than_the_budget_when_assembled_then_no_edge_dangles(self):
        # Given eight neighbours and room for three
        rows = [row("root", letter) for letter in "abcdefgh"]

        # When the graph is assembled
        graph = neighbourhood.assemble(seed(), [rows], limit=4)

        # Then the budget held, and every edge joins two drawn nodes
        assert len(graph["nodes"]) == 4
        drawn = {n["uid"] for n in graph["nodes"]}
        for edge in graph["edges"]:
            assert edge["source"] in drawn and edge["target"] in drawn

    def test_given_a_row_anchored_at_a_refused_node_when_assembled_then_it_is_skipped(self):
        # Given a second hop hanging off a node the budget never admitted
        first = [row("root", letter) for letter in "abc"]
        second = [row("d", "e")]

        # When the graph is assembled
        graph = neighbourhood.assemble(seed(), [first, second], limit=3)

        # Then nothing is drawn from a node that is not there
        assert {n["uid"] for n in graph["nodes"]} == {"root", "a", "b"}
        assert all(e["source"] != "d" and e["target"] != "d"
                   for e in graph["edges"])

    def test_given_a_cap_that_cut_nothing_when_assembled_then_it_is_not_reported(self):
        # Given a group whose every edge was drawn
        # When the graph is assembled
        graph = neighbourhood.assemble(seed(), [[row("root", "a", total=1)]],
                                       limit=10)

        # Then there is nothing to report as truncated
        assert graph["truncated"] == []

    def test_given_a_fan_that_cut_edges_when_assembled_then_the_count_is_reported(self):
        # Given a group the database counted at 121 and sampled at two
        rows = [row("root", letter, total=121) for letter in "ab"]

        # When the graph is assembled
        graph = neighbourhood.assemble(seed(), [rows], limit=10)

        # Then both numbers are reported
        assert graph["truncated"] == [
            {"uid": "root", "type": "REFERENCES_SPELL", "direction": "out",
             "total": 121, "shown": 2}]

    def test_given_both_directions_when_assembled_then_each_is_reported_once(self):
        # Given a truncated group in each direction
        rows = [row("root", "a", total=9), row("root", "b", total=9),
                row("root", "c", outgoing=False, total=9)]

        # When the graph is assembled
        graph = neighbourhood.assemble(seed(), [rows], limit=10)

        # Then a group is reported per direction, not per edge
        assert sorted(t["direction"] for t in graph["truncated"]) == ["in", "out"]


class TestNeighbourhood:
    def test_given_no_seed_when_asked_then_it_is_refused(self):
        # Given neither a section nor a node
        # When the neighbourhood is asked for
        # Then it is refused rather than guessed at
        with pytest.raises(ValueError):
            neighbourhood.neighbourhood()

    def test_given_two_seeds_when_asked_then_it_is_refused(self):
        # Given both ways of naming the seed at once
        # When the neighbourhood is asked for
        # Then exactly one is required
        with pytest.raises(ValueError):
            neighbourhood.neighbourhood(section_id="1", uid="x")

    @pytest.mark.neo4j
    def test_given_a_citation_when_asked_then_it_opens_on_its_own_node(self, graph):
        # Given a cited section
        # When its neighbourhood is asked for
        found = neighbourhood.neighbourhood(section_id="11.2.114", depth=1)

        # Then the seed is at the centre, with the edges around it
        root = next(n for n in found["nodes"] if n["uid"] == found["root"])
        assert root["name"] == "Prone [Condition]"
        assert root["section_id"] == "11.2.114"
        assert root["depth"] == 0
        assert found["edges"]

    @pytest.mark.neo4j
    def test_given_more_depth_when_asked_then_it_reaches_further_but_not_everything(
            self, graph):
        # Given the same seed at one hop and at two
        near = neighbourhood.neighbourhood(section_id="11.2.114", depth=1)
        far = neighbourhood.neighbourhood(section_id="11.2.114", depth=2)

        # When the two are compared
        # Then the further one is bigger, and still inside the node budget
        assert len(far["nodes"]) > len(near["nodes"])
        assert max(n["depth"] for n in far["nodes"]) == 2
        assert len(far["nodes"]) <= neighbourhood.LIMIT

    @pytest.mark.neo4j
    def test_given_a_hub_when_asked_then_it_is_sampled_and_says_what_it_hid(
            self, graph):
        # Given the most-referenced node in the graph
        poison = search.query(
            "MATCH (n:DamageType {name: 'Poison'}) RETURN elementId(n) AS uid",
            {})

        # When its neighbourhood is asked for with a fan of eight
        found = neighbourhood.neighbourhood(uid=poison[0]["uid"], depth=1,
                                            fan=8)

        # Then the sample is eight and the count is honest about the rest
        references = [t for t in found["truncated"]
                      if t["type"] == "REFERENCES_DAMAGE_TYPE"]
        assert references and references[0]["total"] > references[0]["shown"] == 8

    @pytest.mark.neo4j
    def test_given_a_node_with_no_section_id_when_asked_then_it_can_still_expand(
            self, graph):
        # Given a drawn node that is not a section
        found = neighbourhood.neighbourhood(section_id="11.2.114", depth=2)
        term = next(n for n in found["nodes"] if n["section_id"] is None)

        # When it is expanded by its element id
        # Then it opens like any other node
        assert neighbourhood.neighbourhood(uid=term["uid"], depth=1) is not None

    @pytest.mark.neo4j
    def test_given_the_deepest_walk_when_asked_then_every_edge_joins_drawn_nodes(
            self, graph):
        # Given a neighbourhood three hops out
        found = neighbourhood.neighbourhood(section_id="11.2.114", depth=3)

        # When every edge is checked against the nodes returned
        drawn = {n["uid"] for n in found["nodes"]}

        # Then no edge points at something that was never drawn
        for edge in found["edges"]:
            assert edge["source"] in drawn and edge["target"] in drawn

    @pytest.mark.neo4j
    def test_given_the_same_request_twice_when_asked_then_the_sample_is_the_same(
            self, graph):
        # Given the same request made twice
        first = neighbourhood.neighbourhood(section_id="11.2.114", depth=1)
        second = neighbourhood.neighbourhood(section_id="11.2.114", depth=1)

        # When the two are compared
        # Then they are identical
        assert [n["uid"] for n in first["nodes"]] == \
            [n["uid"] for n in second["nodes"]]

    @pytest.mark.neo4j
    def test_given_an_unknown_seed_when_asked_then_it_is_absent_not_empty(
            self, graph):
        # Given an id no section has
        # When its neighbourhood is asked for
        # Then the route can answer 404 rather than draw an empty picture
        assert neighbourhood.neighbourhood(section_id="999.999") is None
