"""
Weapons, armour, adventuring gear — and the table reader they all share.

Equipment is printed as tables, so most of the work is reading cells: costs
in five coinages, weights with vulgar fractions, and a Properties column that
cannot be split on commas because half its values contain them.
"""

from __future__ import annotations

import pytest

from dnd_graph_rag.srd import equipment


class TestParseCost:
    """A price cell, as printed and as gold."""

    def test_given_a_price_in_gold_when_parsed_then_it_is_itself(self):
        # Given a price already in gold
        # When it is parsed
        # Then the printed form and the numeric one agree
        assert equipment.parse_cost("2 GP") == ("2 GP", 2.0)

    @pytest.mark.parametrize("printed,gold", [
        ("4 CP", 0.04), ("5 SP", 0.5), ("2 EP", 1.0), ("1 PP", 10.0),
    ])
    def test_given_a_lesser_coinage_when_parsed_then_it_converts_to_gold(
            self, printed, gold):
        # Given a price in one of the book's five coinages
        # When it is parsed
        # Then it is converted so prices can be compared with one another
        assert equipment.parse_cost(printed) == (printed, gold)

    def test_given_a_thousands_separator_when_parsed_then_it_is_not_a_decimal(self):
        # Given a price written with a comma
        # When it is parsed
        # Then the comma is a separator, not a decimal point
        assert equipment.parse_cost("1,500 GP") == ("1,500 GP", 1500.0)

    def test_given_a_price_that_is_not_a_number_when_parsed_then_only_the_text_survives(self):
        # Given a cell the book leaves as prose
        # When it is parsed
        # Then the printed form is kept and no price is invented
        assert equipment.parse_cost("Varies") == ("Varies", None)

    def test_given_an_empty_cell_when_parsed_then_there_is_nothing_at_all(self):
        # Given a blank cost cell
        # When it is parsed
        # Then neither half claims anything
        assert equipment.parse_cost("") == (None, None)


class TestParseWeight:
    """A weight cell, in pounds."""

    def test_given_whole_pounds_when_parsed_then_the_number_is_read(self):
        # Given a plain weight
        # When it is parsed
        # Then the pounds come back as a number
        assert equipment.parse_weight("3 lb.") == 3.0

    @pytest.mark.parametrize("printed,pounds", [
        ("1¼ lb.", 1.25), ("1½ lb.", 1.5), ("1¾ lb.", 1.75), ("½ lb.", 0.5),
    ])
    def test_given_a_vulgar_fraction_when_parsed_then_it_is_added_on(
            self, printed, pounds):
        # Given a weight written with the fraction the book prints
        # When it is parsed
        # Then the fraction is part of the number
        assert equipment.parse_weight(printed) == pounds

    def test_given_a_dash_when_parsed_then_there_is_no_weight(self):
        # Given the em dash the book uses for weightless items
        # When it is parsed
        # Then no weight is claimed
        assert equipment.parse_weight("—") is None


class TestParseDamage:
    """A weapon's damage cell."""

    def test_given_dice_and_a_type_when_parsed_then_both_are_split_out(self):
        # Given an ordinary weapon damage cell
        # When it is parsed
        # Then the dice and the damage type are separated
        assert equipment.parse_damage("1d8 Slashing") == {"dice": "1d8",
                                                          "type": "Slashing"}

    def test_given_flat_damage_when_parsed_then_it_is_still_read(self):
        """The Blowgun deals a flat 1 Piercing, with no dice at all."""
        # Given the one weapon that rolls nothing
        # When it is parsed
        # Then the flat number is kept where the dice would be
        assert equipment.parse_damage("1 Piercing") == {"dice": "1",
                                                        "type": "Piercing"}

    def test_given_a_cell_that_is_not_damage_when_parsed_then_nothing_is_read(self):
        # Given a cell holding something else
        # When it is parsed
        # Then no damage is invented
        assert equipment.parse_damage("—") is None


class TestSplitProperties:
    """The Properties column, which cannot be split on commas naively."""

    def test_given_plain_properties_when_split_then_each_is_its_own(self):
        # Given a list of simple properties
        # When it is split
        # Then each property stands alone
        assert equipment.split_properties("Finesse, Light") == ["Finesse",
                                                                "Light"]

    def test_given_a_parenthesised_value_when_split_then_it_stays_intact(self):
        """"Ammunition (Range 80/320; Bolt)" is one property, not two."""
        # Given a property whose value contains its own punctuation
        text = "Ammunition (Range 80/320; Bolt), Loading, Two-Handed"

        # When it is split
        properties = equipment.split_properties(text)

        # Then the parenthesised part was never cut open
        assert properties == ["Ammunition (Range 80/320; Bolt)", "Loading",
                              "Two-Handed"]

    def test_given_a_versatile_die_when_split_then_the_die_rides_with_it(self):
        # Given the Versatile property, which carries a die
        # When it is split
        # Then the die stays attached to the property that means it
        assert equipment.split_properties("Versatile (1d10)") == [
            "Versatile (1d10)"]

    def test_given_a_dash_when_split_then_there_are_no_properties(self):
        # Given the em dash the book uses for none
        # When it is split
        # Then the list is empty rather than holding a dash
        assert equipment.split_properties("—") == []


class TestReadTables:
    """Every markdown table in a piece of content, as rows of cells."""

    def test_given_one_table_when_read_then_its_rows_come_back_as_cells(self):
        # Given a markdown table
        content = ("| Name | Cost |\n|---|---|\n"
                   "| Dagger | 2 GP |\n| Club | 1 SP |")

        # When the tables are read
        tables = equipment.read_tables(content)

        # Then there is one table, header first, split into cells
        assert tables == [[["Name", "Cost"], ["Dagger", "2 GP"],
                           ["Club", "1 SP"]]]

    def test_given_prose_between_two_tables_when_read_then_they_stay_apart(self):
        # Given two tables separated by a paragraph
        content = ("| A |\n|---|\n| 1 |\n\nSome prose.\n\n| B |\n|---|\n| 2 |")

        # When the tables are read
        tables = equipment.read_tables(content)

        # Then the prose broke them into two rather than merging them
        assert len(tables) == 2

    def test_given_emphasis_in_a_cell_when_read_then_it_is_stripped_by_default(self):
        # Given a table whose cells carry the book's own emphasis
        content = "| **Name** |\n|---|\n| _Dagger_ |"

        # When the tables are read
        tables = equipment.read_tables(content)

        # Then the words come back without the markers
        assert tables == [[["Name"], ["Dagger"]]]

    def test_given_markup_is_asked_for_when_read_then_it_survives(self):
        """A label can only be told from its value while the markers remain."""
        # Given the same table
        content = "| **Name** |\n|---|\n| _Dagger_ |"

        # When the tables are read keeping the markup
        tables = equipment.read_tables(content, keep_markup=True)

        # Then the emphasis is still there to be read
        assert tables == [[["**Name**"], ["_Dagger_"]]]

    def test_given_no_table_at_all_when_read_then_nothing_comes_back(self):
        # Given prose with no table in it
        # When the tables are read
        # Then the list is empty
        assert equipment.read_tables("Just a paragraph.") == []


class TestFindTable:
    """One logical table, located by its own header row."""

    def test_given_a_matching_header_when_found_then_the_table_is_returned(self):
        # Given a section holding a table
        nodes = [{"heading": "Weapons",
                  "content": "| Name | Damage | Properties |\n|---|---|---|\n"
                             "| Club | 1d4 Bludgeoning | Light |",
                  "subsections": []}]

        # When the table is looked up by its header
        found = equipment.find_table(nodes, ("name", "damage", "properties"))

        # Then the rows and the node that printed them both come back
        rows, node = found
        assert rows[0] == ["Name", "Damage", "Properties"]
        assert node["heading"] == "Weapons"

    def test_given_a_table_continued_on_the_next_page_when_found_then_it_is_one_table(self):
        """
        A long table repeats its header under the page break; the Adventuring
        Gear table runs to 81 items that way.
        """
        # Given the same table printed in two pieces, each with a header
        nodes = [
            {"heading": "Gear", "content": "| Item | Cost |\n|---|---|\n"
                                           "| Rope | 1 GP |", "subsections": []},
            {"heading": "Gear cont.", "content": "| Item | Cost |\n|---|---|\n"
                                                 "| Torch | 1 CP |",
             "subsections": []},
        ]

        # When the table is looked up
        rows, _ = equipment.find_table(nodes, ("item", "cost"))

        # Then the pieces were concatenated under one header
        assert rows == [["Item", "Cost"], ["Rope", "1 GP"], ["Torch", "1 CP"]]

    def test_given_no_matching_header_when_found_then_nothing_comes_back(self):
        # Given a section whose table is a different one
        nodes = [{"heading": "Mounts",
                  "content": "| Mount | Speed |\n|---|---|\n| Pony | 40 |",
                  "subsections": []}]

        # When a different table is looked up
        # Then nothing is returned rather than the wrong table
        assert equipment.find_table(nodes, ("name", "damage")) is None


class TestSubtree:
    """A heading and everything printed under it, flattened."""

    def test_given_a_nested_heading_when_flattened_then_every_descendant_is_included(self):
        # Given a section with children and grandchildren
        nodes = [{"heading": "Weapons", "content": "", "subsections": [
            {"heading": "Simple", "content": "", "subsections": [
                {"heading": "Melee", "content": "", "subsections": []}]}]}]

        # When the subtree is flattened
        flattened = equipment.subtree(nodes, "Weapons")

        # Then the whole branch comes back in document order
        assert [n["heading"] for n in flattened] == ["Weapons", "Simple",
                                                     "Melee"]

    def test_given_a_heading_that_is_not_there_when_flattened_then_it_is_empty(self):
        # Given a tree with no such heading
        # When the subtree is asked for
        # Then the answer is empty rather than an error
        assert equipment.subtree([], "Weapons") == []
