from __future__ import annotations

import pytest

from dnd_graph_rag.srd import statblocks


class TestAbilityModifier:
    @pytest.mark.parametrize("score,modifier", [
        (1, -5), (8, -1), (9, -1), (10, 0), (11, 0), (12, 1), (20, 5), (30, 10),
    ])
    def test_given_a_score_when_converted_then_it_floors_rather_than_truncates(
            self, score, modifier):
        # Given an ability score
        # When the modifier is derived
        # Then odd scores below 10 round down, not towards zero
        assert statblocks.ability_modifier(score) == modifier


class TestAverageHp:
    def test_given_dice_and_a_bonus_when_averaged_then_both_are_counted(self):
        # Given a hit point formula
        # When it is averaged
        # Then the dice average plus the flat bonus, floored
        assert statblocks.average_hp("20d10 + 40") == 150

    def test_given_dice_alone_when_averaged_then_the_bonus_is_zero(self):
        # Given a formula with no modifier
        # When it is averaged
        # Then 3 × 3.5, floored
        assert statblocks.average_hp("3d6") == 10

    def test_given_a_unicode_minus_when_averaged_then_it_subtracts(self):
        # Given a formula written with the SRD's unicode minus
        # When it is averaged
        # Then the sign was understood
        assert statblocks.average_hp("2d6 − 2") == 5

    def test_given_prose_instead_of_dice_when_averaged_then_nothing_is_claimed(self):
        # Given a hit point field that is not a dice expression
        # When it is averaged
        # Then no number is invented for it
        assert statblocks.average_hp("equals the summoner's level") is None


class TestParseSpeed:
    def test_given_a_bare_distance_when_parsed_then_it_is_the_walking_speed(self):
        # Given a speed with no kind named
        # When it is parsed
        # Then the unnamed one is walking, which is what the book means
        assert statblocks.parse_speed("30 ft.") == {"walk": 30}

    def test_given_several_movement_kinds_when_parsed_then_each_is_kept_apart(self):
        # Given a creature that walks, swims and flies
        # When the speed is parsed
        speeds = statblocks.parse_speed("30 ft., Swim 40 ft., Fly 60 ft.")

        # Then each kind carries its own distance
        assert speeds == {"walk": 30, "swim": 40, "fly": 60}


class TestParseBonusList:
    def test_given_several_skills_when_parsed_then_each_carries_its_bonus(self):
        # Given a Skills line
        # When it is parsed
        # Then each skill is keyed in lower case with its number
        assert statblocks.parse_bonus_list("Perception +10, Stealth +5") == {
            "perception": 10, "stealth": 5}

    def test_given_a_unicode_minus_when_parsed_then_the_bonus_is_negative(self):
        # Given a penalty written with the SRD's unicode minus
        # When it is parsed
        # Then the sign survived
        assert statblocks.parse_bonus_list("Stealth −2") == {"stealth": -2}


class TestParseDefenses:
    def test_given_a_semicolon_when_split_then_conditions_follow_it(self):
        # Given a line carrying both
        raw = "Poison; Charmed, Exhaustion, Poisoned"

        # When it is split
        damage, conditions = statblocks.parse_defenses(raw)

        # Then each half went where it belongs
        assert damage == ["Poison"]
        assert conditions == ["Charmed", "Exhaustion", "Poisoned"]

    def test_given_no_semicolon_and_no_conditions_when_split_then_all_are_damage(self):
        # Given a line with no conditions on it
        # When it is split
        # Then nothing is read as a condition
        assert statblocks.parse_defenses("Fire, Cold") == (["Fire", "Cold"], [])

    def test_given_conditions_alone_when_split_then_they_are_conditions(self):
        """Regression: the Knight was immune to "Frightened" damage."""
        # Given a line of conditions, which the book prints without a semicolon
        # When it is split
        # Then they are conditions, not damage types
        assert statblocks.parse_defenses("Frightened") == ([], ["Frightened"])
        assert statblocks.parse_defenses("Charmed, Frightened, Grappled") == (
            [], ["Charmed", "Frightened", "Grappled"])

    def test_given_a_qualified_condition_when_split_then_its_note_is_kept(self):
        # Given a condition immunity with a note
        # When it is split
        damage, conditions = statblocks.parse_defenses(
            "Necrotic; Charmed (with _Mind Blank_), Poisoned")

        # Then it is sorted by its name and keeps the note
        assert damage == ["Necrotic"]
        assert conditions == ["Charmed (with _Mind Blank_)", "Poisoned"]


class TestParseStatBlock:
    @staticmethod
    def _line(markup: str) -> statblocks.Line:
        return statblocks.Line(page=1, x0=0, y0=0, x1=100, y1=10, baseline=8,
                               column=0, text=markup.replace("*", ""),
                               markup=markup, max_size=9.5)

    def test_given_a_field_wrapping_onto_a_second_line_when_parsed_then_it_is_whole(self):
        """Regression: Clay Golem kept two of its six condition immunities."""
        # Given an Immunities line that wraps, and a field after it
        title = self._line("Clay Golem")
        body = [self._line("_Large Construct, Unaligned_"),
                self._line("**Immunities** Acid, Poison; Charmed, Exhaustion,"),
                self._line("Frightened, Paralyzed"),
                self._line("**Senses** Darkvision 60 ft.")]

        # When the stat block is parsed
        record = statblocks.parse_stat_block(title, body, "srd.pdf")

        # Then the continuation joined its field, and the next field is intact
        assert record["immunities"] == ["Acid", "Poison"]
        assert record["condition_immunities"] == [
            "Charmed", "Exhaustion", "Frightened", "Paralyzed"]
        assert record["senses"] == "Darkvision 60 ft."

    def test_given_an_unlabelled_line_before_any_field_when_parsed_then_it_joins_none(
            self):
        # Given the type line, which has no label and comes first
        title = self._line("Knight")
        body = [self._line("_Medium Humanoid, Lawful Good_"),
                self._line("**Immunities** Frightened")]

        # When the stat block is parsed
        record = statblocks.parse_stat_block(title, body, "srd.pdf")

        # Then the type line is not appended to anything
        assert record["condition_immunities"] == ["Frightened"]
        assert record["immunities"] == []


class TestParseAbilities:
    def test_given_a_full_grid_when_parsed_then_every_ability_is_read(self):
        # Given all six abilities as the grid flattens
        raw = ("**Str** 21 +5 +5 **Dex** 10 +0 +0 **Con** 20 +5 +5 "
               "**Int** 3 −4 −4 **Wis** 12 +1 +1 **Cha** 7 −2 −2")

        # When the grid is parsed
        abilities = statblocks.parse_abilities(raw)

        # Then all six are present, with scores, modifiers and saves
        assert set(abilities) == {"str", "dex", "con", "int", "wis", "cha"}
        assert abilities["str"] == {"score": 21, "modifier": 5, "save": 5,
                                    "modifier_valid": True,
                                    "save_has_proficiency": False}

    def test_given_a_save_above_the_modifier_when_parsed_then_proficiency_is_noted(self):
        # Given an ability whose save exceeds its modifier
        raw = ("**Str** 10 +0 +0 **Dex** 14 +2 +5 **Con** 10 +0 +0 "
               "**Int** 10 +0 +0 **Wis** 10 +0 +0 **Cha** 10 +0 +0")

        # When the grid is parsed
        abilities = statblocks.parse_abilities(raw)

        # Then the difference is recorded as proficiency
        assert abilities["dex"]["save_has_proficiency"] is True

    def test_given_a_modifier_that_disagrees_with_its_score_when_parsed_then_it_is_flagged(self):
        # Given a grid whose arithmetic does not hold
        raw = ("**Str** 10 +3 +3 **Dex** 10 +0 +0 **Con** 10 +0 +0 "
               "**Int** 10 +0 +0 **Wis** 10 +0 +0 **Cha** 10 +0 +0")

        # When the grid is parsed
        abilities = statblocks.parse_abilities(raw)

        # Then the disagreement is reported rather than corrected
        assert abilities["str"]["modifier_valid"] is False

    def test_given_a_save_printed_without_its_sign_when_parsed_then_the_grid_survives(self):
        """Young White Dragon prints "Int 6 −2 2"."""
        # Given the grid as the book actually prints it there
        raw = ("**Str** 10 +0 +0 **Dex** 10 +0 +0 **Con** 10 +0 +0 "
               "**Int** 6 −2 2 **Wis** 10 +0 +0 **Cha** 10 +0 +0")

        # When the grid is parsed
        abilities = statblocks.parse_abilities(raw)

        # Then one missing character does not cost all six abilities
        assert abilities is not None
        assert abilities["int"]["save"] == 2

    def test_given_fewer_than_six_abilities_when_parsed_then_nothing_is_returned(self):
        # Given a partial grid, which means the block was misread
        # When it is parsed
        # Then a half-read grid is refused rather than half-stored
        assert statblocks.parse_abilities("**Str** 21 +5 +5") is None


class TestParseChallenge:
    def test_given_a_full_cr_line_when_parsed_then_every_part_is_read(self):
        # Given the most detailed form the book prints
        raw = "**CR** 21 (XP 33,000, or 41,000 in lair; PB +7)"

        # When it is parsed
        challenge = statblocks.parse_challenge(raw)

        # Then the rating, both XP figures and the proficiency bonus are split out
        assert challenge == {"cr": "21", "xp": 33000, "xp_in_lair": 41000,
                             "proficiency_bonus": 7}

    def test_given_a_fractional_rating_when_parsed_then_it_stays_a_fraction(self):
        # Given a low-CR creature
        # When the line is parsed
        # Then the rating is kept as the book writes it
        assert statblocks.parse_challenge(
            "**CR** 1/4 (XP 50; PB +2)")["cr"] == "1/4"

    def test_given_the_xp_before_its_label_when_parsed_then_it_is_still_read(self):
        # Given the handful of places the book writes "2,300 XP"
        # When the line is parsed
        # Then the number is found on either side of the label
        assert statblocks.parse_challenge(
            "**CR** 8 (2,300 XP; PB +3)")["xp"] == 2300

    def test_given_no_cr_at_all_when_parsed_then_nothing_is_claimed(self):
        # Given a line that is not a CR line
        # When it is parsed
        # Then nothing is returned
        assert statblocks.parse_challenge("**HP** 45") == {}


class TestParseEntries:
    def test_given_named_entries_when_split_then_each_keeps_its_own_prose(self):
        # Given two actions printed in one section
        text = ("**_Multiattack._** It attacks twice. "
                "**_Bite._** _Melee Attack Roll:_ +5.")

        # When the section is split
        entries = statblocks.parse_entries(text)

        # Then each name carries only its own description
        assert [e["name"] for e in entries] == ["Multiattack", "Bite"]
        assert entries[0]["description"] == "It attacks twice."

    def test_given_a_trailing_full_stop_in_the_name_when_split_then_it_is_dropped(self):
        # Given the book's own "**_Name._**" form
        # When the section is split
        entries = statblocks.parse_entries("**_Amphibious._** It breathes water.")

        # Then the name is the name, without the punctuation that ended it
        assert entries[0]["name"] == "Amphibious"

    def test_given_unnamed_prose_when_split_then_it_is_one_nameless_entry(self):
        # Given a section that names nothing
        # When it is split
        entries = statblocks.parse_entries("The creature acts twice.")

        # Then the prose is kept, under no name
        assert entries == [{"name": None,
                            "description": "The creature acts twice."}]

    def test_given_nothing_at_all_when_split_then_there_are_no_entries(self):
        # Given an empty section
        # When it is split
        # Then no empty entry is invented for it
        assert statblocks.parse_entries("   ") == []


class TestHasInitiativeAdvantage:
    def test_given_a_permanently_invisible_creature_when_asked_then_it_has_advantage(self):
        """
        The Invisible Stalker prints "+7 (22)": Invisible grants Advantage on
        Initiative.
        """
        # Given a creature whose trait says it is Invisible
        record = {"traits": [{"name": "Invisibility",
                              "description": "The stalker has the Invisible "
                                             "condition."}]}

        # When the stat block is asked
        # Then the trait is what grants it
        assert statblocks.has_initiative_advantage(record) is True

    def test_given_the_condition_taken_by_an_action_when_asked_then_it_does_not_count(self):
        """
        The Will-o'-Wisp turns Invisible as a Bonus Action, after Initiative.
        """
        # Given a creature that becomes Invisible only by acting
        record = {"traits": [],
                  "bonus_actions": [{"name": "Invisibility",
                                     "description": "It has the Invisible "
                                                    "condition."}]}

        # When the stat block is asked
        # Then only a trait counts
        assert statblocks.has_initiative_advantage(record) is False

    def test_given_a_creature_with_no_traits_when_asked_then_it_is_not_an_error(self):
        # Given a stat block carrying no traits at all
        # When it is asked
        # Then the absence is answered
        assert statblocks.has_initiative_advantage({}) is False
