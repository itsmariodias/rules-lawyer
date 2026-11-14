from __future__ import annotations

from dnd_graph_rag.srd.entity_types import type_from_records, type_sections
from dnd_graph_rag.srd.model import Heading, Paragraph, Run, Section, Source, StatBlock
from dnd_graph_rag.srd.sections import build_sections, walk


def subtitle(text: str, page: int) -> Paragraph:
    return Paragraph([Run(text, italic=True)], [page])


def creature(name: str, page: int) -> StatBlock:
    return StatBlock(name, [], [], [], [], [page])


def types(blocks: list) -> dict[str, str]:
    """Each section's heading and type, after building and typing the blocks."""
    sections = build_sections(blocks)
    type_sections(sections)
    return {s.heading: s.entity_type for s in walk(sections)}


class TestTypeSections:
    def test_given_subtitles_when_typed_then_spells_and_items_are_told_apart_from_other_italics(self):
        # Given a spell, a magic item and a feat, each with the italic line under its heading
        blocks = [Heading(1, "Spells", 104), Heading(4, "Acid Arrow", 107), subtitle("Level 2 Evocation (Wizard)", 107),
                  Heading(4, "Bag of Holding", 210), subtitle("Wondrous Item, Uncommon", 210),
                  Heading(4, "Alert", 87), subtitle("Origin Feat", 87)]

        # When typed
        found = types(blocks)

        # Then the subtitle decides, and a feat waits for stage 3
        assert (found["Acid Arrow"], found["Bag of Holding"], found["Alert"]) == ("spell", "magic_item", "rule")

    def test_given_a_stat_block_inside_a_spell_when_typed_then_the_spell_stays_a_spell(self):
        # Given page 109's Animated Object stat block, printed in Animate Objects
        blocks = [Heading(1, "Spells", 104), Heading(4, "Animate Objects", 108),
                  subtitle("Level 5 Transmutation (Bard, Sorcerer, Wizard)", 108), creature("Animated Object", 109)]

        # When typed
        found = types(blocks)

        # Then the stat block is a creature and the spell, outside the monster chapters, no group
        assert (found["Animate Objects"], found["Animated Object"]) == ("spell", "creature")

    def test_given_a_monster_entry_when_typed_then_it_groups_its_stat_blocks(self):
        # Given page 258's Aboleth entry over its stat block
        blocks = [Heading(1, "Monsters A–Z", 258), Heading(2, "Aboleth", 258), Paragraph([Run("Lore.")], [258]),
                  creature("Aboleth", 258)]

        # When typed
        sections = build_sections(blocks)
        type_sections(sections)

        # Then the entry is a group, even over one stat block, and the stat block a creature
        entry = sections[0].subsections[0]
        assert (entry.entity_type, entry.subsections[0].entity_type) == ("creature_group", "creature")

    def test_given_closed_sets_when_typed_then_their_entries_are_typed(self):
        # Given a glossary definition, a trap, and contagions following their set's heading
        blocks = [Heading(1, "Rules Glossary", 176), Heading(2, "Rules Definitions", 176),
                  Heading(4, "Prone [Condition]", 189),
                  Heading(1, "Gameplay Toolbox", 192), Heading(3, "Example Traps", 200),
                  Heading(4, "Hidden Pit", 200), Heading(3, "Magical Contagions", 194),
                  Heading(4, "Example Contagions", 194), Heading(4, "Sight Rot", 195)]

        # When typed
        found = types(blocks)

        # Then each entry has its set's type, and the set headings stay rules
        assert found["Prone [Condition]"] == "glossary_term"
        assert (found["Hidden Pit"], found["Sight Rot"]) == ("trap", "contagion")
        assert (found["Example Traps"], found["Example Contagions"]) == ("rule", "rule")

    def test_given_the_first_pages_when_typed_then_they_are_front_matter(self):
        # Given the legal notice on page 1 and a chapter from page 5
        blocks = [Heading(1, "Legal Information", 1), Heading(1, "Playing the Game", 5)]

        # When typed
        # Then only the first is front matter
        assert types(blocks) == {"Legal Information": "front_matter", "Playing the Game": "rule"}


class TestTypeFromRecords:
    def test_given_records_naming_sections_when_typed_then_only_rules_are_retyped(self):
        # Given a class and its feature as rules, and a feat section already typed a spell
        rage = Section("6.1.3.1", "Level 1: Rage", 4, [], [], Source(28, 28))
        barbarian = Section("6.1", "Barbarian", 2, [], [rage], Source(28, 30))
        odd = Section("8.1", "Alert", 3, [], [], Source(87, 87), "spell")
        classes = [{"section_id": "6.1", "subclasses": [], "features": [{"section_id": "6.1.3.1"}]}]

        # When typed from the records
        type_from_records([barbarian, odd], classes, [], [{"section_id": "8.1"}], [])

        # Then the rules take the records' types and the typed section keeps its own
        assert (barbarian.entity_type, rage.entity_type, odd.entity_type) == ("class", "class_feature", "spell")
