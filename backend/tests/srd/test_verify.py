from __future__ import annotations

import pytest

from dnd_graph_rag.srd.model import (
    Contents,
    Entry,
    Heading,
    Paragraph,
    Run,
    Sidebar,
    StatBlock,
    Table,
)
from dnd_graph_rag.srd.verify import (
    KNOWN,
    check_classes,
    check_contents,
    check_gear,
    check_index,
    check_spells,
    check_weapons,
    listed,
    problems,
)


def entry(name: str, page: int, level: int) -> Entry:
    return Entry([Run(name)], page, level)


def table(caption: str, *rows: tuple[str, ...], header: tuple[str, ...] = ()) -> Table:
    return Table([Run(caption)], [[[Run(h)] for h in header]] if header else [],
                 [[[Run(c)] if c else [] for c in row] for row in rows], [1])


def para(text: str) -> Paragraph:
    return Paragraph([Run(text, italic=True)], [1])


def creature(name: str, page: int) -> StatBlock:
    return StatBlock(name, [], [], [], [], [page])


INDEX = Contents([entry("Aboleth", 258, 2), entry("Gray Ooze", 293, 2)], [2])


class TestCheckIndex:
    def test_given_every_indexed_stat_block_when_checked_then_nothing_is_found(self):
        # Given the indexed stat blocks, and the Giant Fly printed in an item before them
        blocks = [creature("Giant Fly", 222), creature("Aboleth", 258), creature("Gray Ooze", 293)]

        # When checked against the index
        # Then the Giant Fly is not expected and the rest agree
        assert check_index(blocks, INDEX) == []

    def test_given_a_title_misread_when_checked_then_both_sides_are_reported(self):
        # Given "Gray Ooze" read as "GrayOoze"
        blocks = [creature("Aboleth", 258), creature("GrayOoze", 293)]

        # When checked
        # Then the index entry is unfound and the stat block unlisted
        assert check_index(blocks, INDEX) == [
            "Index: Gray Ooze (p. 293) has no stat block on that page",
            "Index: stat block GrayOoze (p. 293) is not listed"]


class TestCheckContents:
    CONTENTS = Contents([entry("Character Origins", 83, 1), entry("Character Backgrounds", 83, 2),
                         entry("Acolyte", 83, 3), entry("Monsters", 254, 1),
                         entry("Running a Monster", 255, 2)], [2])

    def test_given_skipped_levels_and_a_sidebar_when_checked_then_nothing_is_found(self):
        # Given "Acolyte" a level 4 heading under level 2 "Character Backgrounds",
        # and "Running a Monster" a sidebar title (page 255)
        blocks = [Heading(1, "Contents", 2), self.CONTENTS, Heading(1, "Character Origins", 83),
                  Heading(2, "Character Backgrounds", 83), Heading(3, "Background Descriptions", 83),
                  Heading(4, "Acolyte", 83), Heading(1, "Monsters", 254),
                  Sidebar([Run("Running a Monster", bold=True)], [], [255])]

        # When checked
        # Then the Contents agrees
        assert check_contents(blocks, self.CONTENTS) == []

    def test_given_a_heading_read_too_shallow_when_checked_then_it_is_reported(self):
        # Given "Acolyte" read at level 2, beside its parent
        blocks = [Heading(1, "Character Origins", 83), Heading(2, "Character Backgrounds", 83),
                  Heading(2, "Acolyte", 83), Heading(1, "Monsters", 254),
                  Sidebar([Run("Running a Monster")], [], [255])]

        # When checked
        # Then it is not under its parent
        assert check_contents(blocks, self.CONTENTS) == [
            "Contents: Acolyte (p. 83) is a level 2 heading, not under its level 2 parent"]

    def test_given_a_missing_heading_and_an_unlisted_chapter_when_checked_then_both_are_reported(self):
        # Given no "Running a Monster", and a chapter the Contents does not list
        blocks = [Heading(1, "Contents", 2), Heading(1, "Character Origins", 83),
                  Heading(2, "Character Backgrounds", 83), Heading(4, "Acolyte", 83),
                  Heading(1, "Monsters", 254), Heading(1, "Animals", 344)]

        # When checked
        # Then the Contents' own heading is exempt and the others are reported
        assert check_contents(blocks, self.CONTENTS) == [
            "Contents: Running a Monster (p. 255) has no heading on that page after the last match",
            "Contents: chapter Animals (p. 344) is not listed"]


class TestProblems:
    def test_given_no_index_when_checked_then_it_is_an_error(self):
        # Given a Contents but no Index of Stat Blocks
        blocks = [Heading(1, "Contents", 2), Contents([], [2])]

        # When checked
        # Then the missing list is refused by name
        assert listed(blocks, "Contents").pages == [2]
        with pytest.raises(ValueError, match="Index of Stat Blocks"):
            problems(blocks)


class TestCheckSpells:
    LISTS = (table("Cantrips (Level 0 Wizard Spells)", ("Acid Splash", "Evocation", "\u2014")),
             table("Level 2 Wizard Spells", ("Acid Arrow", "Evocation", "\u2014")),
             table("Level 2 Druid Spells", ("Flaming Sphere", "Evocation", "\u2014")))

    def test_given_lists_and_subtitles_agreeing_when_checked_then_nothing_is_found(self):
        # Given page 107's first spells, each listed under its level and school
        blocks = [*self.LISTS, Heading(2, "Spell Descriptions", 107), Heading(4, "Acid Arrow", 107),
                  para("Level 2 Evocation (Wizard)"), Heading(4, "Acid Splash", 107),
                  para("Evocation Cantrip (Wizard)"), Heading(4, "Flaming Sphere", 143),
                  para("Level 2 Evocation (Druid)"), Heading(1, "Rules Glossary", 176)]

        # When checked
        # Then they agree
        assert check_spells(blocks) == []

    def test_given_a_heading_lost_and_a_school_differing_when_checked_then_both_are_reported(self):
        # Given "Acid Splash" merged into its subtitle's paragraph (page 107), and
        # Flaming Sphere's subtitle saying Conjuration as the book prints it
        blocks = [*self.LISTS, Heading(2, "Spell Descriptions", 107), Heading(4, "Acid Arrow", 107),
                  para("Level 2 Evocation (Wizard)"), para("Acid Splash Evocation Cantrip (Wizard)"),
                  Heading(4, "Flaming Sphere", 143), para("Level 2 Conjuration (Druid)")]

        # When checked
        # Then the listed spell is undescribed, and the school difference is a known quirk
        found = check_spells(blocks)
        assert found == ["Spells: Acid Splash is on a class list but not described",
                         "Spells: Flaming Sphere is Level 2 Conjuration, the Druid list says Level 2 Evocation"]
        assert found[1] in KNOWN


class TestCheckClasses:
    HEADER = ("Level", "Proficiency Bonus", "Class Features")

    def blocks(self, *features: str) -> list:
        return [Heading(1, "Classes", 28), Heading(2, "Fighter", 46),
                table("Fighter Features", ("1", "+2", "Fighting Style"), ("2", "+2", "Action Surge (one use)"),
                      ("3", "+2", "Subclass feature"), ("4", "+2", "\u2014"),
                      ("17", "+6", "Action Surge (two uses)"), header=self.HEADER),
                Heading(3, "Fighter Class Features", 47), *(Heading(4, f, 47) for f in features),
                Heading(3, "Fighter Subclass: Champion", 48), Heading(4, "Level 3: Improved Critical", 48),
                Heading(1, "Character Origins", 83)]

    def test_given_repeats_notes_and_a_subclass_when_checked_then_nothing_is_found(self):
        # Given Action Surge described once at 2, listed again at 17 with a note
        blocks = self.blocks("Level 1: Fighting Style", "Level 2: Action Surge")

        # When checked
        # Then the table and headings agree
        assert check_classes(blocks) == []

    def test_given_a_feature_without_its_heading_when_checked_then_both_sides_are_reported(self):
        # Given Action Surge's heading misread as "Level 2: Action"
        blocks = self.blocks("Level 1: Fighting Style", "Level 2: Action")

        # When checked
        # Then both levels of the feature and the stray heading are reported
        assert check_classes(blocks) == [
            "Classes: Fighter level 2 Action Surge has no heading",
            "Classes: Fighter level 17 Action Surge has no heading",
            "Classes: Fighter heading Level 2: Action is not in its table"]


class TestCheckGear:
    def test_given_one_description_pricing_two_rows_when_checked_then_they_agree(self):
        # Given Spell Scroll's description pricing both its rows (page 99)
        blocks = [Heading(2, "Adventuring Gear", 94), Heading(4, "Acid (25 GP)", 94),
                  Heading(4, "Spell Scroll (Cantrip, 30 GP; Level 1, 50 GP)", 99),
                  table("Adventuring Gear", ("Acid", "1 lb.", "25 GP"),
                        ("Spell Scroll (Cantrip)", "\u2014", "30 GP"), ("Spell Scroll (Level 1)", "\u2014", "50 GP")),
                  Heading(2, "Mounts and Vehicles", 100)]

        # When checked
        # Then each row has its description and price
        assert check_gear(blocks) == []

    def test_given_a_price_differing_and_a_row_missing_when_checked_then_both_are_reported(self):
        # Given Acid priced differently, and a description with no row
        blocks = [Heading(2, "Adventuring Gear", 94), Heading(4, "Acid (25 GP)", 94),
                  Heading(4, "Antitoxin (50 GP)", 94), table("Adventuring Gear", ("Acid", "1 lb.", "2 GP"))]

        # When checked
        # Then both are reported
        assert check_gear(blocks) == ["Gear: Antitoxin is described but not in the table",
                                      "Gear: Acid costs 25 GP, the table says 2 GP"]


class TestCheckWeapons:
    def test_given_an_undefined_mastery_when_checked_then_it_is_reported(self):
        # Given Dagger's properties defined and its mastery not
        blocks = [Heading(3, "Properties", 89), Heading(4, "Finesse", 89), Heading(4, "Thrown", 89),
                  Heading(3, "Mastery Properties", 90), Heading(4, "Slow", 90),
                  table("Weapons", ("Simple Melee Weapons", "", "", "", "", ""),
                        ("Dagger", "1d4 Piercing", "Finesse, Thrown (Range 20/60)", "Nick", "1 lb.", "2 GP"))]

        # When checked
        # Then the category row is skipped and the mastery reported
        assert check_weapons(blocks) == ["Weapons: Dagger's Nick is not defined"]
