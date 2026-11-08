from __future__ import annotations

import json

import pytest

from dnd_graph_rag.graph.model import (EdgeBatch, GraphData, NodeBatch,
                                       as_json, clean)


class TestNodeBatch:
    def test_given_labels_when_read_then_the_first_is_the_one_merged_on(self):
        # Given a batch carrying several labels
        batch = NodeBatch(labels=["Section", "Spell"], key="id")

        # When the primary label is read
        # Then it is the first, and the rest are set alongside it
        assert batch.primary == "Section"
        assert batch.signature == "Section:Spell"

    def test_given_a_row_when_added_then_it_is_cleaned_on_the_way_in(self):
        # Given a batch and a row with an empty property
        batch = NodeBatch(labels=["Section"], key="id")

        # When the row is added
        batch.add(id="1", heading="Fireball", content=None)

        # Then the property that would have been stored as null is gone
        assert batch.rows == [{"id": "1", "heading": "Fireball"}]

    def test_given_rows_when_counted_then_the_batch_reports_its_length(self):
        # Given a batch with two rows
        batch = NodeBatch(labels=["Section"], key="id")
        batch.add(id="1")
        batch.add(id="2")

        # When it is measured
        # Then the count is its rows
        assert len(batch) == 2

    def test_given_a_nested_value_when_added_then_the_field_is_named(self):
        # Given a row carrying a nested dict, as the artifact is full of
        batch = NodeBatch(labels=["Creature"], key="name")

        # When it is added
        # Then the failure names the field, which Neo4j's own error does not
        with pytest.raises(TypeError, match="speed"):
            batch.add(name="Goblin", speed={"walk": 30})


class TestEdgeBatch:
    def test_given_an_edge_when_added_then_both_endpoints_are_recorded(self):
        # Given a relationship batch
        batch = EdgeBatch(type="HAS_SUBSECTION", start_label="Section",
                          start_key="id", end_label="Section", end_key="id")

        # When an edge is added
        batch.add("1", "1.1")

        # Then it carries the two keys the loader will match on
        assert batch.rows == [{"start": "1", "end": "1.1", "properties": {}}]

    def test_given_edge_properties_when_added_then_they_are_cleaned_too(self):
        # Given a relationship carrying a property and an empty one
        batch = EdgeBatch(type="HAS_FEATURE", start_label="Class",
                          start_key="name", end_label="Section", end_key="id")

        # When the edge is added
        batch.add("Wizard", "1.1", level=1, subclass=None)

        # Then only what Neo4j would actually store survives
        assert batch.rows[0]["properties"] == {"level": 1}


class TestGraphData:
    @pytest.fixture
    def data(self) -> GraphData:
        sections = NodeBatch(labels=["Section"], key="id")
        sections.add(id="1")
        sections.add(id="2")
        spells = NodeBatch(labels=["Section", "Spell"], key="id")
        spells.add(id="3")
        edges = EdgeBatch(type="HAS_SUBSECTION", start_label="Section",
                          start_key="id", end_label="Section", end_key="id")
        edges.add("1", "2")
        return GraphData(nodes=[sections, spells], edges=[edges])

    def test_given_several_batches_when_counted_then_the_totals_are_across_them(
            self, data):
        # Given a mapped document
        # When the totals are read
        # Then they are the sum over every batch
        assert data.node_count == 3
        assert data.edge_count == 1

    def test_given_batches_when_summarised_then_labels_are_the_exact_set(self):
        # Given batches whose label sets differ
        sections = NodeBatch(labels=["Section"], key="id")
        sections.add(id="1")
        spells = NodeBatch(labels=["Section", "Spell"], key="id")
        spells.add(id="2")
        data = GraphData(nodes=[sections, spells])

        # When the counts are read by label
        counts = data.counts_by_label()

        # Then each exact set is its own entry
        assert counts == {"Section": 1, "Section:Spell": 1}

    def test_given_two_batches_of_one_type_when_summarised_then_they_are_added(self):
        # Given the same relationship type produced by two batches
        first = EdgeBatch(type="DEFINED_IN", start_label="GlossaryTerm",
                          start_key="name", end_label="Section", end_key="id")
        first.add("Fire", "9")
        second = EdgeBatch(type="DEFINED_IN", start_label="Equipment",
                           start_key="name", end_label="Section", end_key="id")
        second.add("Dagger", "8")

        # When the counts are read by type
        counts = GraphData(edges=[first, second]).counts_by_type()

        # Then the type is counted once, across both
        assert counts == {"DEFINED_IN": 2}


class TestClean:
    def test_given_nulls_and_empty_lists_when_cleaned_then_they_are_dropped(self):
        # Given a row with properties that would be stored as null anyway
        # When it is cleaned
        # Then the properties stay sparse, and an empty string is still a value
        assert clean({"a": 1, "b": None, "c": [], "d": ""}) == {"a": 1, "d": ""}

    @pytest.mark.parametrize("value", [1, 1.5, "text", True, ["a", "b"],
                                       [1, 2], [1.5]])
    def test_given_a_value_neo4j_can_hold_when_cleaned_then_it_survives(self, value):
        # Given a primitive or a homogeneous array
        # When it is cleaned
        # Then it passes through untouched
        assert clean({"value": value}) == {"value": value}

    def test_given_a_nested_dict_when_cleaned_then_the_field_is_named(self):
        # Given a row carrying a nested map
        # When it is cleaned
        # Then both the field and the value are in the message
        with pytest.raises(TypeError, match="'resources'"):
            clean({"resources": {"Rages": "3"}})

    def test_given_a_list_of_dicts_when_cleaned_then_it_is_refused(self):
        # Given a damage list, which is a list of maps
        # When it is cleaned
        # Then it is refused here rather than midway through a load
        with pytest.raises(TypeError, match="damage"):
            clean({"damage": [{"dice": "8d6"}]})


class TestAsJson:
    def test_given_a_nested_value_when_serialised_then_it_is_stable(self):
        # Given a structure worth carrying but not worth querying on
        outcomes = {"hit": {"text": "5 Piercing damage"}, "miss": {"text": "None"}}

        # When it is serialised
        serialised = as_json(outcomes)

        # Then it round-trips, and its keys are ordered
        assert json.loads(serialised) == outcomes
        assert serialised.index('"hit"') < serialised.index('"miss"')

    def test_given_non_ascii_when_serialised_then_it_is_kept_readable(self):
        # Given text carrying the book's own punctuation
        # When it is serialised
        # Then it is stored as itself rather than escaped
        assert as_json({"dice": "1d6 − 1"}) == '{"dice": "1d6 − 1"}'

    @pytest.mark.parametrize("empty", [None, {}, []])
    def test_given_nothing_worth_keeping_when_serialised_then_there_is_no_property(
            self, empty):
        # Given an absent or empty structure
        # When it is serialised
        # Then no property is written, rather than the string "null"
        assert as_json(empty) is None
