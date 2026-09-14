"""
The subset of retrieval the agent may call.

Results are prose rather than JSON: the model reads them, and every result
leads with its section id so it can cite what it sees.  The structured half
reaches the UI by another route, so nothing here serialises twice.
"""

from __future__ import annotations

import pytest

from dnd_graph_rag.chat import tools


class TestSearchSrd:
    """Search the SRD for rules text matching a query."""

    def test_given_an_unknown_entity_type_when_called_then_it_never_reaches_the_graph(self):
        # Given a filter naming a type nothing is
        # When the tool is called
        result = tools.search_srd.invoke({"query": "x", "entity_type": "wizardry"})

        # Then the model is told what it may use, rather than getting no results
        assert "Unknown entity_type" in result
        assert "spell" in result

    def test_given_a_question_that_matches_nothing_when_called_then_it_says_so(
            self, graph):
        # Given a loaded graph and a question matching no section
        # When the tool is called
        result = tools.search_srd.invoke({"query": "zzzzqqqq"})

        # Then the model is told to try again rather than left with silence
        assert "No SRD sections matched" in result

    def test_given_a_match_when_called_then_every_result_leads_with_its_id(
            self, graph):
        # Given a loaded graph
        # When the tool is called
        result = tools.search_srd.invoke({"query": "Prone condition"})

        # Then the ids are in front of the passages, where the model will copy them
        assert result.startswith("[")
        assert "[11.2.114]" in result

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
        """
        Deliberately not the full list from the artifact: the long tail
        ("front_matter", "creature_group") narrows nothing anyone would ask.
        """
        # Given the filter the tool offers the model
        # When it is read
        # Then it names the kinds of thing a rules question is about
        assert "spell" in tools.SEARCHABLE_TYPES
        assert "creature" in tools.SEARCHABLE_TYPES
        assert "creature_group" not in tools.SEARCHABLE_TYPES
        assert "front_matter" not in tools.SEARCHABLE_TYPES


class TestGetSrdSection:
    """Fetch the full text of one SRD section by its id."""

    def test_given_an_unknown_id_when_called_then_the_shape_of_one_is_explained(self):
        # Given an id no section has
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
        """So the model can follow a parent or a child it was pointed at."""
        # Given a loaded graph
        # When a section with a parent is fetched
        result = tools.get_srd_section.invoke({"section_id": "11.2.114"})

        # Then the parent is offered by id, ready to be fetched in turn
        assert "Parent: [" in result


class TestTools:
    """What the agent is given."""

    def test_given_the_tool_list_when_read_then_it_is_the_two_ways_in(self):
        # Given the list handed to the agent
        # When it is read
        # Then it is search and one section by id, and nothing else
        assert [tool.name for tool in tools.TOOLS] == ["search_srd",
                                                        "get_srd_section"]

    def test_given_a_tool_when_described_then_its_arguments_are_documented(self):
        """The docstring is what the model reads to decide how to call it."""
        # Given the search tool
        # When its schema is read
        schema = tools.search_srd.args_schema.model_json_schema()

        # Then each argument carries a description
        assert schema["properties"]["query"]["description"]
        assert schema["properties"]["entity_type"]["description"]
