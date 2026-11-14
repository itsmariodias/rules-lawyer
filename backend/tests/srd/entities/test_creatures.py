from __future__ import annotations

from rules_lawyer.srd.entities.creatures import check_mechanics, creature, entries_of
from rules_lawyer.srd.model import (
    Field,
    Paragraph,
    Run,
    Section,
    Source,
    StatBlock,
    StatSection,
)

SCORES = [["Str", "21", "+5", "+5"], ["Dex", "9", "−1", "+3"], ["Con", "15", "+2", "+6"],
          ["Int", "18", "+4", "+8"], ["Wis", "15", "+2", "+6"], ["Cha", "18", "+4", "+4"]]


def entry(name: str, *text: Run) -> Paragraph:
    return Paragraph([Run(f"{name}.", bold=True, italic=True), *text], [258])


def aboleth(fields: list[Field], traits: list[Paragraph] | None = None) -> Section:
    block = StatBlock("Aboleth", [Run("Large Aberration, Lawful Evil", italic=True)], fields, SCORES,
                      [StatSection("Traits", traits or [])], [258])
    return Section("15.1.1", "Aboleth", 3, [block], [], Source(258, 258, 100, 900), "creature")


class TestCreature:
    def test_given_a_stat_block_when_recorded_then_its_fields_are_parsed(self):
        # Given page 258's Aboleth fields
        fields = [Field("AC", [Run("17")]), Field("Initiative", [Run("+7 (17)")]),
                  Field("HP", [Run("150 (20d10 + 40)")]), Field("Speed", [Run("10 ft., Swim 40 ft.")]),
                  Field("Immunities", [Run("Poison; Charmed, Frightened")]),
                  Field("Senses", [Run("Darkvision 120 ft.; Passive Perception 20")]),
                  Field("CR", [Run("10 (XP 5,900, or 7,200 in lair; PB +4)")])]

        # When recorded
        record = creature(aboleth(fields), "SRD.pdf")

        # Then each field is read, immunities are sorted by name, and nothing is wrong
        assert (record["type"], record["alignment"], record["ac"]) == ("Large Aberration", "Lawful Evil", 17)
        assert record["hp"] == {"average": 150, "formula": "20d10 + 40", "calculated": 150, "valid": True}
        assert record["speed"] == {"walk": 10, "swim": 40}
        assert (record["immunities"], record["condition_immunities"]) == (["Poison"], ["Charmed", "Frightened"])
        assert (record["cr"], record["xp"], record["xp_in_lair"], record["proficiency_bonus"]) == ("10", 5900, 7200, 4)
        assert record["abilities"]["dex"] == {"score": 9, "modifier": -1, "save": 3, "modifier_valid": True,
                                              "save_has_proficiency": True}
        assert record["initiative"] == {"bonus": 7, "score": 17, "advantage": False, "valid": True}
        assert record["warnings"] == []

    def test_given_an_initiative_implying_advantage_when_recorded_then_it_is_corrected_and_warned(self):
        # Given page 293's Gray Ooze: +5 implied, nothing granting Advantage
        record = creature(aboleth([Field("Initiative", [Run("−2 (13)")])]), "SRD.pdf")

        # When recorded
        # Then the computed score is used and the printed one kept
        assert record["initiative"] == {"bonus": -2, "score": 8, "advantage": False, "valid": False,
                                        "printed_score": 13}
        assert record["warnings"] == [("printed Initiative score 13 implies Advantage on Initiative, "
                                       "but no trait grants it; using 8 (10 -2)")]

    def test_given_a_trait_making_it_invisible_when_recorded_then_advantage_counts(self):
        # Given the Invisible Stalker: +7 (22) and a trait keeping it Invisible
        traits = [entry("Invisibility", Run(" The stalker has the Invisible condition."))]

        # When recorded
        record = creature(aboleth([Field("Initiative", [Run("+7 (22)")])], traits), "SRD.pdf")

        # Then 22 is right
        assert (record["initiative"]["advantage"], record["initiative"]["valid"]) == (True, True)


class TestEntriesOf:
    def test_given_spell_lists_after_spellcasting_when_read_then_they_join_its_description(self):
        # Given the Lich's Spellcasting and its bold, not italic, "At Will:" list
        paragraphs = [entry("Spellcasting", Run(" The lich casts one of the following spells:")),
                      Paragraph([Run("At Will:", bold=True), Run(" "), Run("Mage Hand", italic=True)], [304])]

        # When read
        # Then it is one entry, the list in its description
        assert entries_of(paragraphs) == [{"name": "Spellcasting", "description":
                                           "The lich casts one of the following spells: **At Will:** _Mage Hand_"}]


class TestCheckMechanics:
    def test_given_a_wrong_average_and_bonus_when_checked_then_both_are_reported(self):
        # Given an average one off its dice and a bonus no ability gives
        record = {"name": "Test", "proficiency_bonus": 2,
                  "abilities": {"str": {"modifier": 3}, "dex": {"modifier": 1}},
                  "actions": [{"name": "Claw", "attack": {"kind": "melee", "bonus": 9},
                               "damage": [{"average": 8, "dice": "2d6", "type": "Slashing"}]}]}

        # When checked
        found = check_mechanics([record])

        # Then each is counted and reported
        assert found == {"damage_averages_checked": 1, "damage_average_mismatches": ["Test/Claw: 8 vs 2d6"],
                         "attack_bonuses_checked": 1, "attack_bonus_mismatches": ["Test/Claw: +9"]}
