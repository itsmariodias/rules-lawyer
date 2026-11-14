from __future__ import annotations

from dnd_graph_rag.srd.entities.references import (
    Names,
    mentions,
    references,
    run_lists,
    unresolved,
)
from dnd_graph_rag.srd.model import (
    Field,
    Paragraph,
    Run,
    Section,
    Source,
    StatBlock,
    StatSection,
    Table,
)

SPELLS = Names(["Fireball", "Cure Wounds"])
ITEMS = Names(["Spell Scroll"])
CREATURES = Names(["Ghast", "Riding Horse"])


def section(id: str, heading: str, entity_type: str, *blocks, spell: dict | None = None) -> Section:
    return Section(id, heading, 4, list(blocks), [], Source(1, 1), entity_type, spell=spell)


class TestNames:
    def test_given_plurals_and_punctuation_when_resolved_then_the_name_is_found(self):
        # Given "two Ghasts" and a name with a stop after it
        # When resolved
        # Then the singular is found, and an unknown word is not
        assert (CREATURES.resolve("Ghasts"), SPELLS.resolve("Fireball."), SPELLS.resolve("Fire")) == (
            "Ghast", "Fireball", None)


class TestMentions:
    def test_given_styled_names_when_scanned_then_italics_are_spells_or_items_and_bold_creatures(self):
        # Given a spell and an item in italics, a creature in bold, and an italic word naming nothing
        runs = [Run("Cast "), Run("Fireball", italic=True), Run(" or read a "), Run("Spell Scroll", italic=True),
                Run(" to stop the "), Run("Riding Horse", bold=True), Run(", "), Run("quickly", italic=True)]

        # When scanned
        # Then each styled name is its kind, and emphasis names nothing
        assert mentions(runs, SPELLS, ITEMS, CREATURES) == [
            ("spell", "Fireball"), ("magic_item", "Spell Scroll"), ("creature", "Riding Horse")]

    def test_given_fixed_phrases_when_scanned_then_lists_sized_areas_and_damage_are_found(self):
        # Given a condition list, an action, a damage type and a sized area, and "Attack" as a word
        runs = [Run("Attack anyone in a 20-foot Cone: they have the Deafened and Frightened conditions, "
                    "take Fire damage, and can take the Dash action.")]

        # When scanned
        found = mentions(runs, SPELLS, ITEMS, CREATURES)

        # Then every listed name counts and the bare word does not
        assert sorted(found) == [("action", "Dash"), ("area_of_effect", "Cone"), ("condition", "Deafened"),
                                 ("condition", "Frightened"), ("damage_type", "Fire")]


class TestRunLists:
    def test_given_a_table_when_listed_then_each_cell_is_its_own_text(self):
        # Given a class spell list row
        table = Table([Run("Level 1 Bard Spells", bold=True)], [[[Run("Spell", bold=True)]]],
                      [[[Run("Cure Wounds", italic=True)], [Run("Abjuration")]]], [33])

        # When listed
        # Then the caption, header and both cells are texts
        assert [[r.text for r in runs] for runs in run_lists(table)] == [
            ["Level 1 Bard Spells"], ["Spell"], ["Cure Wounds"], ["Abjuration"]]


class TestReferences:
    def test_given_a_spell_imposing_a_condition_when_referenced_then_it_imposes_rather_than_mentions(self):
        # Given a spell whose text imposes Frightened and mentions Prone
        text = Paragraph([Run("The target has the Frightened condition. A Prone condition target is immune.")], [1])
        spell = section("10.3.1", "Fear", "spell", text, spell={"conditions_imposed": ["Frightened"]})

        # When referenced
        found = {(e["target"]["name"], e["relation"]) for e in references([spell])}

        # Then the imposed condition is imposes_condition, the other a reference
        assert found == {("Frightened", "imposes_condition"), ("Prone", "references_condition")}

    def test_given_a_creature_entry_when_referenced_then_its_source_names_the_part(self):
        # Given a ghoul whose Claw paralyzes
        claw = Paragraph([Run("Claw.", bold=True, italic=True),
                          Run(" The target has the Paralyzed condition until the end of its next turn.")], [288])
        block = StatBlock("Ghoul", [], [Field("AC", [Run("12")])], [], [StatSection("Actions", [claw])], [288])
        ghoul = section("15.40.1", "Ghoul", "creature", block)

        # When referenced
        entry_edges = [e for e in references([ghoul]) if "part" in e["source"]]

        # Then the entry's edge names the part and imposes the condition
        assert entry_edges == [{"source": {"type": "creature", "name": "Ghoul", "part": "actions/Claw"},
                                "target": {"type": "condition", "name": "Paralyzed"},
                                "relation": "imposes_condition"}]


class TestUnresolved:
    def test_given_an_edge_to_nothing_extracted_when_checked_then_it_is_reported(self):
        # Given a spell section, and edges to it and to a spell that does not exist
        sections = [section("10.3.1", "Fireball", "spell")]
        edges = [{"target": {"type": "spell", "name": "Fireball"}},
                 {"target": {"type": "spell", "name": "Wish"}},
                 {"target": {"type": "condition", "name": "Prone"}}]

        # When checked against the sections and a glossary of one condition
        # Then only the missing spell is reported
        assert unresolved(edges, sections, [{"name": "Prone", "term_type": "condition"}]) == ["spell Wish"]
