from __future__ import annotations

from rules_lawyer.srd.entities.spells import components, magic_item, spell
from rules_lawyer.srd.model import Paragraph, Run, Section, Source


def field(label: str, value: str) -> Paragraph:
    return Paragraph([Run(f"{label}:", bold=True), Run(f" {value}")], [125])


def section(subtitle: str, *blocks: Paragraph) -> Section:
    return Section("10.3.1", "Test", 4, [Paragraph([Run(subtitle, italic=True)], [125]), *blocks], [],
                   Source(125, 125))


class TestSpell:
    def test_given_a_spells_fields_when_read_then_ritual_and_concentration_are_split_off(self):
        # Given a ritual with concentration
        found = spell(section("Level 1 Divination (Bard, Wizard)",
                              field("Casting Time", "Action or Ritual"), field("Range", "Self"),
                              field("Component", "V"), field("Duration", "Concentration, up to 10 minutes"),
                              Paragraph([Run("Each creature makes a Wisdom saving throw.")], [125])))

        # When read
        # Then the subtitle, both flags and the save are found
        assert (found["level"], found["school"], found["classes"]) == (1, "Divination", ["Bard", "Wizard"])
        assert (found["ritual"], found["casting_time"]) == (True, "Action")
        assert (found["concentration"], found["duration"]) == (True, "up to 10 minutes")
        assert found["components"] == {"verbal": True, "somatic": False, "material": None}
        assert found["saving_throw"] == "Wisdom"

    def test_given_a_cantrip_when_read_then_its_level_is_0(self):
        # Given a cantrip's subtitle
        # When read
        # Then it is level 0 of its school
        assert spell(section("Evocation Cantrip (Sorcerer, Wizard)"))["level"] == 0


class TestComponents:
    def test_given_a_costly_consumed_material_when_read_then_cost_and_use_are_found(self):
        # Given Revivify's components (page 159)
        # When read
        # Then the cost in GP and that it is consumed are found
        assert components("V, S, M (a diamond worth 300+ GP, which the spell consumes)") == {
            "verbal": True, "somatic": True, "material": "a diamond worth 300+ GP, which the spell consumes",
            "material_cost_gp": 300, "material_consumed": True}


class TestMagicItem:
    def test_given_a_subtitle_with_attunement_when_read_then_it_is_split_into_parts(self):
        # Given a weapon requiring attunement by a class
        found = magic_item(section("Weapon (Any Sword), Very Rare (Requires Attunement by a Paladin)"))

        # When read
        # Then category, subtype, rarity and the requirement are separate
        assert found == {"category": "Weapon", "subtype": "Any Sword", "rarity": "Very Rare",
                         "requires_attunement": True, "attunement_requirement": "a Paladin"}
