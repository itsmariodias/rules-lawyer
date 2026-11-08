from __future__ import annotations

import pytest

from dnd_graph_rag.srd import mechanics


class TestParseUses:
    def test_given_a_recharge_range_when_parsed_then_both_faces_are_kept(self):
        # Given an entry named with a recharge range
        name = "Fire Breath (Recharge 5–6)"

        # When the uses are parsed
        uses = mechanics.parse_uses(name)

        # Then the type and the faces it recharges on are both recorded
        assert uses == {"type": "recharge", "printed": "Recharge 5–6",
                        "recharge_on": [5, 6]}

    def test_given_a_single_recharge_face_when_parsed_then_the_range_is_that_face(self):
        # Given a recharge on one face only
        # When the uses are parsed
        uses = mechanics.parse_uses("Web (Recharge 5)")

        # Then the range is that face twice, so callers need no special case
        assert uses["recharge_on"] == [5, 5]

    def test_given_a_daily_limit_when_parsed_then_the_count_is_read(self):
        # Given an entry limited per day
        # When the uses are parsed
        uses = mechanics.parse_uses("Teleport (3/Day)")

        # Then the number of times is recorded
        assert uses == {"type": "per_day", "printed": "3/Day", "times": 3}

    def test_given_a_name_with_no_limit_when_parsed_then_there_is_nothing(self):
        # Given an ordinary entry name
        # When the uses are parsed
        # Then nothing is invented
        assert mechanics.parse_uses("Multiattack") is None

    def test_given_no_name_at_all_when_parsed_then_it_is_not_an_error(self):
        # Given an entry with no name
        # When the uses are parsed
        # Then the absence is answered rather than raised
        assert mechanics.parse_uses("") is None


class TestStripUses:
    def test_given_a_name_carrying_a_limit_when_stripped_then_only_the_name_is_left(self):
        # Given a name with a recharge printed after it
        # When the limit is stripped
        # Then what remains is the name alone
        assert mechanics.strip_uses("Fire Breath (Recharge 5–6)") == "Fire Breath"

    def test_given_a_name_with_no_limit_when_stripped_then_it_is_unchanged(self):
        # Given a name with nothing to strip
        # When it is stripped
        # Then it comes back as it went in
        assert mechanics.strip_uses("Multiattack") == "Multiattack"


class TestParseDamage:
    def test_given_a_stat_blocks_average_and_dice_when_parsed_then_both_are_read(self):
        # Given the form a stat block prints
        text = "_Hit:_ 12 (2d6 + 5) Bludgeoning damage."

        # When the damage is parsed
        damage = mechanics.parse_damage(text)

        # Then the average, the dice and the type are all captured
        assert damage == [{"average": 12, "dice": "2d6 + 5",
                           "type": "Bludgeoning"}]

    def test_given_two_instances_when_parsed_then_both_appear_in_order(self):
        # Given an entry dealing two kinds of damage
        text = "7 (1d8 + 3) Piercing damage plus 3 (1d6) Poison damage."

        # When the damage is parsed
        damage = mechanics.parse_damage(text)

        # Then both are returned, in the order the book prints them
        assert [d["type"] for d in damage] == ["Piercing", "Poison"]

    def test_given_a_spells_bare_dice_when_parsed_then_the_average_is_absent(self):
        # Given the form a spell prints, with no average
        # When the damage is parsed
        damage = mechanics.parse_damage("takes 8d6 Fire damage")

        # Then the dice are read and the average is left empty
        assert damage == [{"average": None, "dice": "8d6", "type": "Fire"}]

    def test_given_averages_are_not_wanted_when_parsed_then_only_the_spell_form_matches(self):
        # Given a caller reading a spell
        # When spell-shaped and stat-block-shaped text are each parsed
        spell = mechanics.parse_damage("8d6 Fire damage", with_average=False)
        statblock = mechanics.parse_damage("12 (2d6 + 5) Bludgeoning damage",
                                           with_average=False)

        # Then only the spell's own form is read
        assert spell == [{"average": None, "dice": "8d6", "type": "Fire"}]
        assert statblock == []

    def test_given_a_unicode_minus_when_parsed_then_it_becomes_an_ascii_one(self):
        # Given dice written with the SRD's unicode minus
        # When the damage is parsed
        damage = mechanics.parse_damage("3 (1d6 − 1) Piercing damage")

        # Then the dice are storable and computable
        assert damage[0]["dice"] == "1d6 - 1"

    def test_given_no_damage_at_all_when_parsed_then_the_list_is_empty(self):
        # Given prose that deals no damage
        # When it is parsed
        # Then nothing is found
        assert mechanics.parse_damage("The creature moves 30 feet.") == []


class TestConditionsImposed:
    def test_given_a_pair_joined_by_and_when_scanned_then_both_are_imposed(self):
        """Regression: the Tarrasque's Thunderous Bellow imposed nothing."""
        # Given an outcome inflicting two conditions at once
        text = ("_Failure:_ 78 (12d12) Thunder damage, and the target has "
                "the Deafened and Frightened conditions until the end of "
                "its next turn.")

        # When it is scanned
        # Then both are imposed, not neither
        assert mechanics.conditions_imposed(text) == ["Deafened", "Frightened"]

    def test_given_a_list_of_three_when_scanned_then_every_one_is_imposed(self):
        # Given an outcome inflicting three conditions
        text = "the target has the Blinded, Deafened, and Poisoned conditions."

        # When it is scanned
        # Then the serial comma does not cost the middle one
        assert mechanics.conditions_imposed(text) == ["Blinded", "Deafened",
                                                      "Poisoned"]

    def test_given_a_page_marker_inside_a_pair_when_scanned_then_it_is_ignored(
            self):
        """
        The Remorhaz's swallow has a page break between its two conditions.
        """
        # Given a pair split by the marker the markdown carries
        text = ("A swallowed creature has the Blinded\n\n<!-- PAGE:320 -->"
                "\n\nand Restrained conditions.")

        # When it is scanned
        # Then the break in the page is not a break in the sentence
        assert mechanics.conditions_imposed(text) == ["Blinded", "Restrained"]

    def test_given_conditions_joined_by_or_when_scanned_then_none_is_imposed(
            self):
        """An *or* list is usually target eligibility, not an effect."""
        # Given a list of conditions describing which targets are eligible
        text = ("you can wrap a Chain around an unwilling creature within 5 "
                "feet of yourself that has the Grappled, Incapacitated, or "
                "Restrained condition")

        # When it is scanned
        # Then nothing is imposed
        assert mechanics.conditions_imposed(text) == []

    def test_given_an_outcome_when_scanned_then_the_condition_is_imposed(self):
        # Given a stat block stating an outcome
        text = "the target has the Prone condition"

        # When the conditions are read
        # Then it counts as inflicted
        assert mechanics.conditions_imposed(text) == ["Prone"]

    def test_given_a_scope_that_ends_at_a_comma_when_scanned_then_it_is_imposed(self):
        # Given a qualifier in a clause of its own
        text = "While Charmed, the target has the Incapacitated condition."

        # When the conditions are read
        # Then the qualifier does not reach the clause that inflicts
        assert mechanics.conditions_imposed(text) == ["Incapacitated"]

    def test_given_a_qualifier_in_the_same_clause_when_scanned_then_nothing_is_imposed(self):
        # Given a duration rather than an outcome
        text = "The target is Restrained while the vampire has the " \
               "Incapacitated condition."

        # When the conditions are read
        # Then nothing was inflicted by it
        assert mechanics.conditions_imposed(text) == []

    def test_given_target_eligibility_when_scanned_then_nothing_is_imposed(self):
        # Given a phrase describing which targets qualify
        text = "one creature within 5 feet that has the Prone condition"

        # When the conditions are read
        # Then it describes the target, not what happens to it
        assert mechanics.conditions_imposed(text) == []

    def test_given_an_immunity_when_scanned_then_nothing_is_imposed(self):
        # Given a creature that cannot be given the condition
        text = "It is immune to anything that has the Charmed condition."

        # When the conditions are read
        # Then the immunity is not read as an infliction
        assert mechanics.conditions_imposed(text) == []

    def test_given_a_condition_stated_twice_when_scanned_then_it_appears_once(self):
        # Given the same condition inflicted in two sentences
        text = ("The target has the Poisoned condition. "
                "The target has the Poisoned condition again.")

        # When the conditions are read
        # Then the list is deduplicated
        assert mechanics.conditions_imposed(text) == ["Poisoned"]

    def test_given_a_saving_throw_alternative_when_scanned_then_it_is_imposed(self):
        # Given a spell's save-or-suffer phrasing
        text = ("The target must succeed on a Wisdom saving throw or have "
                "the Paralyzed condition.")

        # When the conditions are read
        # Then the failure outcome counts as inflicted
        assert mechanics.conditions_imposed(text) == ["Paralyzed"]


class TestParseEntryMechanics:
    def test_given_a_melee_attack_when_parsed_then_kind_bonus_and_reach_are_read(self):
        # Given an ordinary melee attack
        description = ("_Melee Attack Roll:_ +5, reach 5 ft. _Hit:_ 7 (1d8 + 3) "
                       "Piercing damage.")

        # When the entry is parsed
        parsed = mechanics.parse_entry_mechanics("Bite", description)

        # Then the attack is structured
        assert parsed["attack"] == {"kind": "melee", "bonus": 5, "reach_ft": 5}

    def test_given_a_ranged_attack_when_parsed_then_both_ranges_are_read(self):
        # Given an attack with a normal and a long range
        description = "_Ranged Attack Roll:_ +4, range 30/120 ft. _Hit:_ 4 damage."

        # When the entry is parsed
        parsed = mechanics.parse_entry_mechanics("Sling", description)

        # Then both distances are kept apart
        assert parsed["attack"]["range_ft"] == {"normal": 30, "long": 120}

    def test_given_a_single_range_when_parsed_then_the_long_range_is_absent(self):
        # Given an attack printed with one distance
        description = "_Ranged Attack Roll:_ +4, range 60 ft. _Hit:_ 4 damage."

        # When the entry is parsed
        parsed = mechanics.parse_entry_mechanics("Spit", description)

        # Then nothing is invented for the long range
        assert parsed["attack"]["range_ft"] == {"normal": 60, "long": None}

    def test_given_a_parenthesised_note_when_parsed_then_it_is_kept(self):
        # Given an attack qualified in parentheses
        description = ("_Melee Attack Roll:_ +7 (with Advantage), reach 10 ft. "
                       "_Hit:_ 9 damage.")

        # When the entry is parsed
        parsed = mechanics.parse_entry_mechanics("Claw", description)

        # Then the qualification survives beside the bonus
        assert parsed["attack"]["note"] == "with Advantage"

    def test_given_a_saving_throw_when_parsed_then_ability_dc_and_targets_are_read(self):
        # Given an entry that calls for a save
        description = ("_Constitution Saving Throw:_ DC 15, each creature in "
                       "a 30-foot Cone. _Failure:_ 22 (4d10) Fire damage.")

        # When the entry is parsed
        parsed = mechanics.parse_entry_mechanics("Fire Breath", description)

        # Then the save is structured, and who it hits with it
        assert parsed["save"]["ability"] == "Constitution"
        assert parsed["save"]["dc"] == 15
        assert parsed["save"]["targets"] == "each creature in a 30-foot Cone"

    def test_given_labelled_outcomes_when_parsed_then_each_becomes_its_own_entry(self):
        # Given an entry with a failure and a success
        description = ("_Dexterity Saving Throw:_ DC 13. _Failure:_ 7 (2d6) "
                       "Fire damage. _Success:_ Half damage.")

        # When the entry is parsed
        parsed = mechanics.parse_entry_mechanics("Blast", description)

        # Then each labelled outcome is separately readable, with its damage
        assert set(parsed["outcomes"]) == {"failure", "success"}
        assert parsed["outcomes"]["failure"]["damage"][0]["dice"] == "2d6"

    def test_given_an_entry_with_a_recharge_when_parsed_then_the_uses_ride_along(self):
        # Given a limited-use entry
        # When it is parsed
        parsed = mechanics.parse_entry_mechanics(
            "Fire Breath (Recharge 5–6)", "_Failure:_ 24 (7d6) Fire damage.")

        # Then the limit is part of the mechanics
        assert parsed["uses"]["type"] == "recharge"

    def test_given_an_entry_stating_nothing_mechanical_when_parsed_then_it_is_empty(self):
        # Given flavour text
        # When it is parsed
        parsed = mechanics.parse_entry_mechanics("Amphibious",
                                                 "The creature can breathe air and water.")

        # Then nothing is claimed about it
        assert parsed == {}


class TestAnnotateCreatures:
    def test_given_creatures_with_entries_when_annotated_then_each_entry_gains_them(self):
        # Given a creature with one parseable action
        creatures = [{"actions": [
            {"name": "Bite",
             "description": "_Melee Attack Roll:_ +5, reach 5 ft. "
                            "_Hit:_ 7 (1d8 + 3) Piercing damage."}]}]

        # When the creatures are annotated
        annotated = mechanics.annotate_creatures(creatures)

        # Then the entry carries the structure, and the count reports it
        assert annotated == 1
        assert creatures[0]["actions"][0]["attack"]["bonus"] == 5

    def test_given_an_entry_with_no_mechanics_when_annotated_then_it_is_untouched(self):
        # Given a purely descriptive trait
        creatures = [{"traits": [{"name": "Amphibious",
                                  "description": "It breathes water."}]}]

        # When the creatures are annotated
        annotated = mechanics.annotate_creatures(creatures)

        # Then nothing was added and nothing was counted
        assert annotated == 0
        assert set(creatures[0]["traits"][0]) == {"name", "description"}

    def test_given_a_creature_with_no_entries_at_all_when_annotated_then_nothing_happens(self):
        # Given a stat block with none of the entry lists
        creatures = [{"name": "Rock"}]

        # When the creatures are annotated
        # Then it is not an error
        assert mechanics.annotate_creatures(creatures) == 0


class TestParseSpellMechanics:
    def test_given_a_save_in_prose_when_parsed_then_the_ability_is_read(self):
        # Given a spell describing its save the way the book writes it
        text = "Each creature must succeed on a Dexterity saving throw."

        # When the spell is parsed
        parsed = mechanics.parse_spell_mechanics(text)

        # Then the ability is captured, capitalised as the graph stores it
        assert parsed["saving_throw"] == "Dexterity"

    def test_given_a_spell_attack_when_parsed_then_its_kind_is_read(self):
        # Given a spell that attacks rather than calling for a save
        text = "Make a ranged spell attack against the target."

        # When the spell is parsed
        parsed = mechanics.parse_spell_mechanics(text)

        # Then the kind of attack is recorded
        assert parsed["attack"] == {"kind": "ranged"}

    def test_given_spell_damage_when_parsed_then_no_average_is_invented(self):
        # Given a spell's damage, which the book prints without an average
        text = "The target takes 8d6 Fire damage."

        # When the spell is parsed
        parsed = mechanics.parse_spell_mechanics(text)

        # Then only the dice are claimed
        assert parsed["damage"] == [{"average": None, "dice": "8d6",
                                     "type": "Fire"}]

    def test_given_a_condition_inflicted_when_parsed_then_it_is_recorded(self):
        # Given a spell that inflicts a condition on a failed save
        text = ("On a failed save, the target has the Blinded condition "
                "for 1 minute.")

        # When the spell is parsed
        parsed = mechanics.parse_spell_mechanics(text)

        # Then the condition rides along with the rest
        assert parsed["conditions_imposed"] == ["Blinded"]

    def test_given_prose_with_no_mechanics_when_parsed_then_it_is_empty(self):
        # Given a purely utilitarian spell
        # When it is parsed
        # Then nothing is claimed about it
        assert mechanics.parse_spell_mechanics(
            "You touch a creature and it gains 5 temporary hit points.") == {}
