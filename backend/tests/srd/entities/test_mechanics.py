from __future__ import annotations

from dnd_graph_rag.srd.entities.mechanics import (
    average,
    conditions_imposed,
    damage,
    entry_mechanics,
    labelled_parts,
    spell_mechanics,
    uses,
)
from dnd_graph_rag.srd.model import Run


def label(text: str) -> Run:
    return Run(text, italic=True)


class TestAverage:
    def test_given_dice_when_averaged_then_the_mean_is_floored(self):
        # Given the Aboleth's hit dice, and prose that is not dice
        # When averaged
        # Then dice give the floored mean, prose nothing
        assert average("20d10 + 40") == 150
        assert average("2d6 − 1") == 6
        assert average("Medium or smaller") is None


class TestUses:
    def test_given_entry_names_when_read_then_limits_are_typed(self):
        # Given a recharge, a per-day limit, and no limit
        # When read
        # Then each is typed with its numbers
        assert uses("Acid Breath (Recharge 5–6)") == {"type": "recharge", "printed": "Recharge 5–6",
                                                      "recharge_on": [5, 6]}
        assert uses("Dominate Mind (2/Day)") == {"type": "per_day", "printed": "2/Day", "times": 2}
        assert uses("Multiattack") is None


class TestDamage:
    def test_given_stat_block_and_spell_damage_when_read_then_both_forms_are_found(self):
        # Given a stat block's "average (dice) type" and a spell's dice alone
        # When read
        # Then the average is kept where printed, None where not
        assert damage("12 (2d6 + 5) Bludgeoning damage plus 4 (1d8) Necrotic damage") == [
            {"average": 12, "dice": "2d6 + 5", "type": "Bludgeoning"},
            {"average": 4, "dice": "1d8", "type": "Necrotic"}]
        assert damage("takes 8d6 Fire damage", with_average=False) == [
            {"average": None, "dice": "8d6", "type": "Fire"}]


class TestConditionsImposed:
    def test_given_inflicted_and_mentioned_conditions_when_read_then_only_inflicted_count(self):
        # Given an and-list inflicted, and a condition named as a prerequisite
        text = ("Each creature has the Deafened and Frightened conditions. "
                "One creature within 5 feet that has the Prone condition takes damage.")

        # When read
        # Then both inflicted conditions count, the prerequisite does not
        assert conditions_imposed(text) == ["Deafened", "Frightened"]


class TestLabelledParts:
    def test_given_a_colon_set_roman_when_split_then_the_label_still_counts(self):
        # Given the Magmin's "Failure" with its colon outside the italics (page 305)
        runs = [label("Dexterity Saving Throw:"), Run(" DC 11, each creature. "), label("Failure"),
                Run(": 7 (2d6) Fire damage.")]

        # When split
        # Then both labels head their text
        assert labelled_parts(runs) == [(None, ""), ("Dexterity Saving Throw", " DC 11, each creature. "),
                                        ("Failure", " 7 (2d6) Fire damage.")]


class TestEntryMechanics:
    def test_given_an_attack_when_read_then_bonus_reach_and_hit_are_found(self):
        # Given the Aboleth's Tentacle
        runs = [label("Melee Attack Roll:"), Run(" +9, reach 15 ft. "), label("Hit:"),
                Run(" 12 (2d6 + 5) Bludgeoning damage. If the target is Large or smaller, it has the Grappled "
                    "condition (escape DC 14).")]

        # When read
        found = entry_mechanics("Tentacle", runs)

        # Then the attack, its outcome, its damage and the condition it imposes are found
        assert found["attack"] == {"kind": "melee", "bonus": 9, "reach_ft": 15}
        assert found["outcomes"]["hit"]["damage"] == [{"average": 12, "dice": "2d6 + 5", "type": "Bludgeoning"}]
        assert found["conditions_imposed"] == ["Grappled"]

    def test_given_a_save_when_read_then_dc_targets_and_each_outcome_are_found(self):
        # Given the Aboleth's Consume Memories, a save with failure and success
        runs = [label("Intelligence Saving Throw:"), Run(" DC 16, one creature within 30 feet. "),
                label("Failure:"), Run(" 10 (3d6) Psychic damage. "), label("Success:"), Run(" Half damage.")]

        # When read
        found = entry_mechanics("Consume Memories", runs)

        # Then the save and both outcomes are separate
        assert found["save"] == {"ability": "Intelligence", "dc": 16, "targets": "one creature within 30 feet"}
        assert list(found["outcomes"]) == ["failure", "success"]

    def test_given_a_summoned_creatures_prose_bonus_when_read_then_no_attack_is_recorded(self):
        # Given the Animated Object's Slam, its bonus prose (page 109)
        runs = [label("Melee Attack Roll:"), Run(" Bonus equals your spell attack modifier, reach 5 ft.")]

        # When read
        # Then there is no attack to record
        assert "attack" not in entry_mechanics("Slam", runs)


class TestSpellMechanics:
    def test_given_spell_prose_when_read_then_save_and_damage_are_found(self):
        # Given a line of Fireball's description
        text = "Each creature in a 20-foot-radius Sphere makes a Dexterity saving throw, taking 8d6 Fire damage."

        # When read
        # Then the save and the dice are found
        assert spell_mechanics(text) == {"saving_throw": "Dexterity",
                                         "damage": [{"average": None, "dice": "8d6", "type": "Fire"}]}
