"""
The JSON → graph translation.  No database.

``mapping`` is where every decision about the graph lives — what becomes a
node, what folds into a section, what is matched rather than merged — so this
is where the coverage belongs; the loader below it only batches and writes.

The helpers below read a built ``GraphData`` the way an assertion wants to:
by label set, by a matching row, or by relationship type.
"""

from __future__ import annotations

import json

import pytest

from dnd_graph_rag.graph import mapping


def rows_for(data, *labels) -> list[dict]:
    for batch in data.nodes:
        if batch.labels == list(labels):
            return batch.rows
    raise AssertionError(f"no batch for {labels}: {data.counts_by_label()}")


def one(data, *labels, **match) -> dict:
    found = [row for row in rows_for(data, *labels)
             if all(row.get(k) == v for k, v in match.items())]
    assert len(found) == 1, f"expected one {labels} matching {match}, got {found}"
    return found[0]


def count_with(data, *labels) -> int:
    """Rows in every batch carrying at least these labels, folded ones too."""
    wanted = set(labels)
    return sum(len(b) for b in data.nodes if wanted <= set(b.labels))


def edges_of(data, type_: str) -> list[dict]:
    return [row for batch in data.edges if batch.type == type_
            for row in batch.rows]


class TestWalk:
    """Every node of the section tree, in document order."""

    def test_given_a_nested_tree_when_walked_then_parents_come_first(self):
        # Given a tree two levels deep
        tree = [{"id": "1", "subsections": [{"id": "1.1", "subsections": []}]}]

        # When it is walked
        # Then each node is visited once, parent before child
        assert [n["id"] for n in mapping.walk(tree)] == ["1", "1.1"]


class TestAbilityKey:
    """The key a `:CreatureAbility` node merges on."""

    def test_given_a_creature_and_an_entry_when_keyed_then_it_matches_the_reference(
            self, tiny_document):
        """
        A creature-sourced reference names the entry it came from in ``part``
        ("actions/Bite"), and the key is that same string — without it all
        1542 of those edges would smear across the whole stat block.
        """
        # Given a reference naming the part it came from
        part = tiny_document["references"][0]["source"]["part"]

        # When the ability key is built from the creature and the entry
        key = mapping.ability_key("Goblin", "actions", "Bite")

        # Then it is the creature and that same part
        assert key == f"Goblin|{part}"

    def test_given_a_built_document_when_looked_up_then_the_node_carries_that_key(
            self, tiny_document):
        # Given the mapped document
        data = mapping.build(tiny_document)

        # When the ability is looked up by the key a reference would use
        # Then exactly one node answers to it
        assert one(data, "CreatureAbility", key="Goblin|actions/Bite")


class TestMapperLookup:
    """Resolving a reference target's name to the node that holds it."""

    def test_given_a_name_printed_twice_when_looked_up_then_the_real_entity_wins(
            self, tiny_document):
        """"Deck of Illusions" is printed twice; the one with metadata is it."""
        # Given a document with the same magic item name on two sections
        mapper = mapping.Mapper(tiny_document)
        mapping.add_sections(mapper)

        # When the name is resolved
        resolved = mapper.lookup("magic_item", "Deck of Illusions")

        # Then it is the section carrying the item block, not the table above it
        assert resolved == "4"

    def test_given_the_duplicate_when_built_then_nothing_is_warned_about(
            self, tiny_document):
        # Given the same document
        # When it is built
        data = mapping.build(tiny_document)

        # Then the duplicate resolved cleanly rather than being reported
        assert not any("Deck of Illusions" in w for w in data.warnings)


class TestBuildSections:
    """The section tree, which is the spine of the graph."""

    def test_given_typed_sections_when_built_then_each_gains_its_entity_label(
            self, tiny_document):
        """A spell is not a `:Spell` beside its section — it *is* the section."""
        # Given a document of typed sections
        # When it is built
        counts = mapping.build(tiny_document).counts_by_label()

        # Then the entity type is a second label on the section node
        assert counts["Section:CreatureGroup"] == 1
        assert counts["Section:Spell"] == 1
        assert counts["Section:MagicItem"] == 2

    def test_given_a_section_when_built_then_it_keeps_its_offsets(self, tiny_document):
        """
        What makes the graph usable for retrieval rather than only for
        counting: anything a traversal finds resolves back to its own text.
        """
        # Given the mapped document
        # When a section node is read
        spell = one(mapping.build(tiny_document), "Section", "Spell")

        # Then it carries the range that slices the markdown, and its page
        assert (spell["char_start"], spell["char_end"]) == (100, 200)
        assert spell["page_start"] == 3

    def test_given_a_subsection_when_built_then_it_becomes_a_structural_edge(
            self, tiny_document):
        # Given a section with a child
        # When it is built
        edges = edges_of(mapping.build(tiny_document), "HAS_SUBSECTION")

        # Then the tree is in the graph as edges
        assert {"start": "1", "end": "1.1"} == {k: v for k, v in edges[0].items()
                                                if k != "properties"}

    def test_given_a_spell_when_built_then_its_block_is_flattened_onto_it(
            self, tiny_document):
        # Given a section carrying a spell block
        # When it is built
        spell = one(mapping.build(tiny_document), "Section", "Spell")

        # Then the block's fields are properties of the section itself
        assert spell["level"] == 3
        assert spell["school"] == "Evocation"
        assert spell["verbal"] is True
        assert spell["material"] == "bat guano"

    def test_given_a_damage_list_when_built_then_it_becomes_parallel_arrays(
            self, tiny_document):
        """Neo4j stores no nested maps, and a damage list's parts correspond
        by position."""
        # Given a spell that deals damage
        # When it is built
        spell = one(mapping.build(tiny_document), "Section", "Spell")

        # Then the three components line up index by index
        assert spell["damage_dice"] == ["8d6"]
        assert spell["damage_types"] == ["Fire"]
        assert spell["damage_averages"] == [28]

    def test_given_dice_with_no_average_when_built_then_no_average_is_stored(
            self, tiny_document):
        """A sentinel would read as a number the book never printed."""
        # Given a spell whose damage has no printed average
        tiny_document["sections"][1]["spell"]["damage"] = [
            {"average": None, "dice": "8d6", "type": "Fire"}]

        # When it is built
        mapped = one(mapping.build(tiny_document), "Section", "Spell")

        # Then the dice are stored and the averages property is absent
        assert mapped["damage_dice"] == ["8d6"]
        assert "damage_averages" not in mapped


class TestBuildCreatures:
    """Stat blocks, and the abilities references point at."""

    def test_given_a_stat_block_when_built_then_it_folds_into_its_section(
            self, tiny_document):
        """
        A stat block *is* its section, so a second node would store the same
        paragraph twice and draw every edge from it twice over.
        """
        # Given a creature whose name matches its section's heading
        # When the document is built
        data = mapping.build(tiny_document)

        # Then there is one node, carrying both halves
        assert len(rows_for(data, "Section", "Creature")) == 1
        creature = one(data, "Section", "Creature")
        assert creature["id"] == "1.1"
        assert creature["content"] == "A goblin."
        assert creature["ac"] == 15
        assert creature["cr"] == "1/4"

    def test_given_a_creatures_speed_and_abilities_when_built_then_they_are_flattened(
            self, tiny_document):
        # Given a stat block with a speed map and an ability grid
        # When it is built
        creature = one(mapping.build(tiny_document), "Section", "Creature")

        # Then each becomes its own queryable property
        assert creature["speed_walk"] == 30
        assert creature["speed_climb"] == 20
        assert creature["str_score"] == 10

    def test_given_a_creature_with_no_section_when_built_then_the_load_fails(
            self, tiny_document):
        """
        336 stat blocks on both sides with unique names is the invariant; a
        creature with nothing to fold into means the two have diverged.
        """
        # Given a creature whose name matches no section
        tiny_document["creatures"][0]["name"] = "Hobgoblin"

        # When the document is built
        # Then it fails loudly rather than silently storing an orphan
        with pytest.raises(ValueError, match="diverged"):
            mapping.build(tiny_document)

    def test_given_an_ability_when_built_then_its_mechanics_are_flattened(
            self, tiny_document):
        # Given an action with parsed mechanics
        # When it is built
        bite = one(mapping.build(tiny_document), "CreatureAbility",
                   key="Goblin|actions/Bite")

        # Then the attack and its damage are properties, and the rest is JSON
        assert bite["attack_bonus"] == 4
        assert bite["reach_ft"] == 5
        assert bite["damage_dice"] == ["1d6+2"]
        assert json.loads(bite["outcomes_json"])["hit"]["text"] == \
            "5 Piercing damage"

    def test_given_a_two_part_range_when_built_then_it_becomes_two_properties(
            self, tiny_document):
        # Given a ranged attack with a normal and a long range
        # When it is built
        sling = one(mapping.build(tiny_document), "CreatureAbility",
                    key="Goblin|actions/Sling")

        # Then each distance is filterable on its own
        assert sling["range_ft"] == 30
        assert sling["range_long_ft"] == 120


class TestBuildGlossary:
    """The typed terms the rest of the book points at."""

    def test_given_a_term_when_built_then_its_type_becomes_a_label(
            self, tiny_document):
        # Given glossary entries of two types
        # When they are built
        data = mapping.build(tiny_document)

        # Then each carries a label naming what it is
        assert one(data, "GlossaryTerm", "DamageType", name="Fire")
        assert one(data, "GlossaryTerm", "Condition", name="Charmed")


class TestBuildEquipment:
    """Weapons, armour, gear and poisons."""

    def test_given_an_item_printed_as_a_section_when_built_then_it_folds_in(
            self, tiny_document):
        """
        Gear and poisons are printed as a heading with prose, so they *are*
        that section — the reason ``extract_poisons`` records ``section_id``.
        """
        # Given a poison naming the section that prints it
        # When the document is built
        folded = one(mapping.build(tiny_document),
                     "Section", "Rule", "Equipment", "Poison")

        # Then one node carries the section's offsets and the item's properties
        assert folded["id"] == "5"
        assert folded["char_start"] == 500
        assert folded["heading"] == "Serpent Venom (200 GP)"
        assert folded["name"] == "Serpent Venom"
        assert folded["cost_gp"] == 200.0
        assert folded["poison_type"] == "Injury"

    def test_given_an_item_with_no_section_when_built_then_it_is_its_own_node(
            self, tiny_document):
        # Given a weapon, which is only ever a table row
        # When the document is built
        data = mapping.build(tiny_document)

        # Then it has nothing to fold into and stays a node of its own
        assert one(data, "Equipment", "Weapon", name="Dagger")


class TestBuildClasses:
    """Classes, their levels and the features they grant."""

    def test_given_a_levels_resources_when_built_then_they_become_two_arrays(
            self, tiny_document):
        """Neo4j stores no nested maps; the two correspond by position."""
        # Given a class level carrying a resources map
        # When it is built
        level = one(mapping.build(tiny_document), "ClassLevel", key="Wizard|1")

        # Then the names and the values are parallel arrays
        assert level["resource_names"] == ["Cantrips", "Prepared Spells"]
        assert level["resource_values"] == ["3", "4"]
        assert level["proficiency_bonus"] == 2


class TestBuildReferences:
    """The book's own cross-references, as edges."""

    def test_given_a_creature_sourced_reference_when_built_then_it_lands_on_the_ability(
            self, tiny_document):
        """
        Otherwise "which creatures can Frighten, and *how*" loses its second
        half: the edge would smear across the whole stat block.
        """
        # Given a reference naming the action it came from
        # When the document is built
        edges = edges_of(mapping.build(tiny_document), "IMPOSES_CONDITION")

        # Then the edge starts at that action, not at the creature
        assert edges == [{"start": "Goblin|actions/Bite", "end": "Charmed",
                          "properties": {}}]

    def test_given_a_target_type_when_built_then_it_is_bridged_to_the_term(
            self, tiny_document):
        # Given a reference to a damage type
        # When the document is built
        edges = edges_of(mapping.build(tiny_document), "REFERENCES_DAMAGE_TYPE")

        # Then it resolves to the glossary term of that name
        assert {"start": "2", "end": "Fire"}.items() <= edges[0].items()

    def test_given_a_target_that_resolves_to_nothing_when_built_then_it_is_reported(
            self, tiny_document):
        """
        Merging on a name that fails to resolve would invent an empty node
        and hide exactly the drift this stage exists to catch.
        """
        # Given a reference to a condition nothing defines
        # When the document is built
        data = mapping.build(tiny_document)

        # Then no edge is drawn, and the miss is counted rather than merged
        assert edges_of(data, "REFERENCES_CONDITION") == []
        assert data.unresolved == [{"end": "target",
                                    "relation": "REFERENCES_CONDITION",
                                    "type": "condition", "name": "Nonexistent",
                                    "part": ""}]


class TestBuildDerived:
    """Edges already implied by parsed list fields."""

    def test_given_a_creatures_defences_when_built_then_they_become_edges(
            self, tiny_document):
        # Given a creature with immunities and carried gear
        # When the document is built
        data = mapping.build(tiny_document)

        # Then each list becomes an edge to the entity it named
        assert edges_of(data, "IMMUNE_TO")[0]["end"] == "Fire"
        assert edges_of(data, "IMMUNE_TO_CONDITION")[0]["end"] == "Charmed"
        assert edges_of(data, "CARRIES")[0]["end"] == "Dagger"

    def test_given_a_poison_when_built_then_it_links_to_the_type_explaining_it(
            self, tiny_document):
        """
        Nothing refers to a poison type, so without this edge the paragraph
        defining "Injury" is unreachable from the poison it describes.
        """
        # Given a poison naming its delivery type
        # When the document is built
        data = mapping.build(tiny_document)

        # Then the type is a node, joined to the poison
        assert one(data, "GlossaryTerm", "PoisonType", name="Injury")
        assert edges_of(data, "HAS_POISON_TYPE") == [
            {"start": "Serpent Venom", "end": "Injury", "properties": {}}]

    def test_given_a_spells_class_list_when_built_then_it_becomes_edges(
            self, tiny_document):
        # Given a spell whose subtitle names a class
        # When the document is built
        edges = edges_of(mapping.build(tiny_document), "ON_SPELL_LIST")

        # Then the class list is traversable
        assert {"start": "2", "end": "Wizard"}.items() <= edges[0].items()


class TestBuildAgainstTheRealArtifact:
    """The mapper held against the artifact's own statement of its contents."""

    def test_given_the_artifact_when_mapped_then_the_counts_are_what_it_claims(
            self, document):
        # Given the artifact and the counts it carries
        data = mapping.build(document)
        counts = document["meta"]["counts"]
        by_label = data.counts_by_label()

        # When the mapped batches are counted by label
        # Then every collection maps to exactly what the parser counted
        assert count_with(data, "Section") == counts["sections"]
        for entity_type, expected in counts["entity_types"].items():
            label = mapping.SECTION_LABELS[entity_type]
            assert count_with(data, "Section", label) == expected
        assert count_with(data, "Creature") == counts["creatures"]
        assert count_with(data, "Equipment") == counts["equipment"]
        assert count_with(data, "GlossaryTerm") == counts["glossary"]
        assert by_label["Class"] == counts["classes"]
        assert by_label["Species"] == counts["species"]
        assert by_label["Background"] == counts["backgrounds"]
        assert by_label["Feat"] == counts["feats"]

    def test_given_the_artifact_when_mapped_then_every_reference_resolves(
            self, document):
        # Given the artifact
        data = mapping.build(document)

        # When the references are mapped
        relations = {r["relation"].upper() for r in document["references"]}
        mapped = sum(count for type_, count in data.counts_by_type().items()
                     if type_ in relations)

        # Then nothing was dropped and nothing was warned about
        assert data.unresolved == []
        assert data.warnings == []
        assert mapped == len(document["references"])

    def test_given_the_artifact_when_mapped_then_no_equipment_is_stored_twice(
            self, document):
        """
        Before the extractors recorded ``section_id`` this was 95 duplicated
        nodes and 60 duplicated edges, and "which things deal Poison damage"
        counted Serpent Venom twice.
        """
        # Given every section's prose, keyed by its own content
        sections = {n["content"]: n["id"]
                    for n in mapping.walk(document["sections"])}

        # When each item's description is looked for among them
        # Then an item that repeats a section's prose names that section
        for item in document["equipment"]:
            description = item.get("description")
            if description and description in sections:
                assert item.get("section_id") == sections[description], (
                    f"{item['name']} repeats section {sections[description]} "
                    "without naming it")

    def test_given_the_artifact_when_mapped_then_a_folded_item_is_scanned_once(
            self, document):
        # Given the items that fold into a section
        folded = {e["name"] for e in document["equipment"] if e.get("section_id")}

        # When the reference sources are read
        sourced = {r["source"]["name"] for r in document["references"]
                   if r["source"]["type"] in ("gear", "poison")}

        # Then a folded item's prose was scanned as its section, not twice
        assert not (folded & sourced)
