from __future__ import annotations

import pytest

from dnd_graph_rag.srd.model import (
    Contents,
    Entry,
    Heading,
    ListBlock,
    Paragraph,
    Run,
    Section,
    Sidebar,
    StatBlock,
    Table,
)
from dnd_graph_rag.srd.sections import build_sections, walk


def paragraph(text: str, page: int) -> Paragraph:
    return Paragraph([Run(text)], [page])


def table(caption: str, page: int) -> Table:
    return Table([Run(caption, bold=True)], [[[Run("Name", bold=True)]]], [[[Run("Club")]]], [page])


def outline(sections: list[Section]) -> list[tuple[str, int, str]]:
    """(id, level, heading) of every section, in reading order."""
    return [(s.id, s.level, s.heading) for s in walk(sections)]


class TestBuildSections:
    def test_given_headings_when_built_then_they_nest_by_level_with_dotted_ids(self):
        # Given a chapter, two sections, and a subsection under the second
        blocks = [Heading(1, "Playing the Game", 5), paragraph("Rhythm.", 5),
                  Heading(2, "The Six Abilities", 5), Heading(2, "D20 Tests", 6),
                  Heading(3, "Ability Checks", 6), paragraph("Checks.", 7)]

        # When built
        sections = build_sections(blocks)

        # Then each heading opens a section under the last shallower one, numbered from 1
        assert outline(sections) == [("1", 1, "Playing the Game"), ("1.1", 2, "The Six Abilities"),
                                     ("1.2", 2, "D20 Tests"), ("1.2.1", 3, "Ability Checks")]
        assert sections[0].blocks == [paragraph("Rhythm.", 5)]
        assert (sections[0].source.page_start, sections[0].source.page_end) == (5, 7)

    def test_given_a_float_mid_section_when_built_then_it_follows_the_sections_own_blocks(self):
        # Given page 109's Animate Objects: text, the Animated Object stat block, more text
        creature = StatBlock("Animated Object", [], [], [], [], [109])
        blocks = [Heading(4, "Animate Objects", 108), paragraph("Objects animate.", 108), creature,
                  paragraph("Using a Higher-Level Spell Slot.", 109)]

        # When built
        sections = build_sections(blocks)

        # Then the stat block is a section one level down, after both paragraphs
        assert outline(sections) == [("1", 4, "Animate Objects"), ("1.1", 5, "Animated Object")]
        assert len(sections[0].blocks) == 2
        assert sections[0].subsections[0].blocks == [creature]

    def test_given_a_block_before_any_heading_when_built_then_it_is_an_error(self):
        # Given a paragraph with no heading above it
        # When built
        # Then it is refused, naming its page
        with pytest.raises(ValueError, match="page 3"):
            build_sections([paragraph("Orphan.", 3)])


class TestPlaceFloats:
    def test_given_a_table_printed_after_the_last_subsection_when_built_then_it_ends_its_namer(self):
        # Given page 91: "Weapons" names its table, which is printed after Vex, the last mastery
        blocks = [Heading(1, "Equipment", 89), Heading(2, "Weapons", 89), paragraph("See the Weapons table.", 89),
                  Heading(3, "Mastery Properties", 90), Heading(4, "Vex", 90), paragraph("Advantage.", 90),
                  table("Weapons", 91)]

        # When built
        # Then the table is the last subsection of the section naming it
        assert outline(build_sections(blocks))[1:] == [
            ("1.1", 2, "Weapons"), ("1.1.1", 3, "Mastery Properties"), ("1.1.1.1", 4, "Vex"),
            ("1.1.2", 3, "Weapons")]

    def test_given_a_table_printed_before_its_namer_when_built_then_it_opens_it(self):
        # Given page 28: Barbarian Features printed in "As a Level 1 Character",
        # named by the paragraph opening "Barbarian Class Features"
        blocks = [Heading(1, "Classes", 28), Heading(2, "Barbarian", 28), Heading(4, "As a Level 1 Character", 28),
                  ListBlock(False, [[paragraph("Gain features listed in the Barbarian Features table.", 28)]],
                            [28]),
                  table("Barbarian Features", 28),
                  Heading(3, "Barbarian Class Features", 28),
                  paragraph("These features are listed in the Barbarian Features table.", 28),
                  Heading(4, "Level 1: Rage", 28)]

        # When built
        # Then it is the first subsection of the paragraph's section; the list's mention owns nothing
        assert outline(build_sections(blocks))[1:] == [
            ("1.1", 2, "Barbarian"), ("1.1.1", 4, "As a Level 1 Character"),
            ("1.1.2", 3, "Barbarian Class Features"), ("1.1.2.1", 4, "Barbarian Features"),
            ("1.1.2.2", 4, "Level 1: Rage")]

    def test_given_a_table_only_a_list_names_when_built_then_it_stays_where_printed(self):
        # Given page 28's Core Barbarian Traits, printed first in the class, named only in a list
        blocks = [Heading(1, "Classes", 28), Heading(2, "Barbarian", 28), table("Core Barbarian Traits", 28),
                  Heading(4, "As a Level 1 Character", 28),
                  ListBlock(False, [[paragraph("Gain all the traits in the Core Barbarian Traits table.", 28)]],
                            [28])]

        # When built
        # Then it stays with the class
        assert outline(build_sections(blocks))[1:3] == [("1.1", 2, "Barbarian"), ("1.1.1", 3, "Core Barbarian Traits")]

    def test_given_a_sidebar_the_contents_lists_when_built_then_it_goes_where_listed(self):
        # Given page 255's "Running a Monster", printed in Resistances and Vulnerabilities,
        # listed under Monsters after Parts of a Stat Block
        contents = Contents([Entry([Run("Monsters", bold=True)], 254, 1),
                             Entry([Run("Parts of a Stat Block")], 254, 2),
                             Entry([Run("Running a Monster")], 255, 2)], [2])
        blocks = [Heading(1, "Contents", 2), contents, Heading(1, "Monsters", 254),
                  Heading(2, "Parts of a Stat Block", 254), Heading(3, "Resistances and Vulnerabilities", 255),
                  Sidebar([Run("Running a Monster", bold=True)], [paragraph("Act.", 255)], [255])]

        # When built
        # Then it follows Parts of a Stat Block, under Monsters
        assert outline(build_sections(blocks))[1:] == [
            ("2", 1, "Monsters"), ("2.1", 2, "Parts of a Stat Block"),
            ("2.1.1", 3, "Resistances and Vulnerabilities"), ("2.2", 2, "Running a Monster")]
