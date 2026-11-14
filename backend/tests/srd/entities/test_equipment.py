from __future__ import annotations

from dnd_graph_rag.srd.entities.equipment import gear, price, weapons, weight_lb
from dnd_graph_rag.srd.model import Paragraph, Run, Section, Source, Table


def cells(*texts: str) -> list[list[Run]]:
    return [[Run(text)] if text else [] for text in texts]


def float_section(id: str, table: Table) -> Section:
    return Section(id, "Weapons", 3, [table], [], Source(91, 91))


class TestPrice:
    def test_given_prices_when_read_then_they_are_kept_and_converted_to_gold(self):
        # Given copper, a thousands separator, and no price
        # When read
        # Then each is kept as printed, with its value in gold pieces
        assert price("4 CP") == {"cost": "4 CP", "cost_gp": 0.04}
        assert price("1,000 GP") == {"cost": "1,000 GP", "cost_gp": 1000.0}
        assert price("Varies") == {"cost": "Varies", "cost_gp": None}


class TestWeightLb:
    def test_given_weights_when_read_then_fractions_count_and_dashes_are_none(self):
        # Given a fractional weight and an unweighed item
        # When read
        # Then the fraction is added, and a dash is no weight
        assert weight_lb("1½ lb.") == 1.5
        assert weight_lb("\u2014") is None


class TestWeapons:
    def test_given_the_weapons_table_when_read_then_each_row_has_its_category(self):
        # Given page 91's table: a category row, the Club under it, and the Blowgun's flat damage
        table = Table([Run("Weapons", bold=True)], [], [
            cells("Simple Melee Weapons", "", "", "", "", ""),
            cells("Club", "1d4 Bludgeoning", "Light", "Slow", "2 lb.", "1 SP"),
            cells("Martial Ranged Weapons", "", "", "", "", ""),
            cells("Blowgun", "1 Piercing", "Ammunition (Range 25/100; Needle), Loading", "Vex", "1 lb.", "10 GP")],
            [91], [None, 0, None, 2])

        # When read
        club, blowgun = weapons(float_section("9.2.5", table), "SRD.pdf")

        # Then the category comes from the row each is under, and commas in parentheses stay
        assert (club["category"], club["damage"], club["cost_gp"]) == (
            "Simple Melee", {"dice": "1d4", "type": "Bludgeoning"}, 0.1)
        assert blowgun["damage"] == {"dice": "1", "type": "Piercing"}
        assert blowgun["properties"] == ["Ammunition (Range 25/100; Needle)", "Loading"]


class TestGear:
    def test_given_an_item_without_a_row_when_read_then_its_heading_prices_it(self):
        # Given Acid with its table row, and Spell Scroll priced only in its heading
        table = Table([Run("Adventuring Gear", bold=True)], [], [cells("Acid", "1 lb.", "25 GP")], [94])
        table_section = Section("9.5.1", "Adventuring Gear", 3, [table], [], Source(94, 94))
        acid = Section("9.5.2", "Acid (25 GP)", 4, [Paragraph([Run("Throw it.")], [94])], [], Source(94, 94))
        scroll = Section("9.5.70", "Spell Scroll (Cantrip, 30 GP; Level 1, 50 GP)", 4, [], [], Source(99, 99))
        parent = Section("9.5", "Adventuring Gear", 2, [], [table_section, acid, scroll], Source(94, 99))

        # When read
        found = gear(parent, table_section, "SRD.pdf")

        # Then the table is skipped, Acid takes its row, and the scroll its heading's first price
        assert [(g["name"], g["weight_lb"], g["cost_gp"], g["section_id"]) for g in found] == [
            ("Acid", 1.0, 25.0, "9.5.2"), ("Spell Scroll", None, 30.0, "9.5.70")]
        assert found[0]["description"] == "Throw it."
