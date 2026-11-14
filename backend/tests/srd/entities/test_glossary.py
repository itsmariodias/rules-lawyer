from __future__ import annotations

import pytest

from rules_lawyer.srd.entities.glossary import glossary
from rules_lawyer.srd.model import Paragraph, Run, Section, Source, Table
from rules_lawyer.srd.vocabulary import Action, AreaOfEffect, Condition, TermType

DAMAGE_TYPES = ["Acid", "Bludgeoning", "Cold", "Fire", "Force", "Lightning", "Necrotic", "Piercing", "Poison",
                "Psychic", "Radiant", "Slashing", "Thunder"]


def terms(*leave_out: str) -> list[Section]:
    """A glossary section per condition, action and area of effect, but those named."""
    found = []
    for term_type, vocabulary in ((TermType.CONDITION, Condition), (TermType.ACTION, Action),
                                  (TermType.AREA_OF_EFFECT, AreaOfEffect)):
        for name in vocabulary:
            if name not in leave_out:
                found.append(Section("11.2.1", f"{name} [{term_type.title()}]", 4, [], [], Source(176, 176),
                                     "glossary_term", term=name, term_type=term_type))
    return found


def damage_table(*names: str) -> Section:
    table = Table([Run("Damage Types", bold=True)], [], [[[Run(name)], [Run("Examples")]] for name in names], [180])
    return Section("11.2.46.1", "Damage Types", 5, [table], [], Source(180, 180))


def poison() -> Section:
    return Section("12.6", "Poison", 2, [Paragraph([Run("Poisons come in the following four types:")], [197]),
                                         Paragraph([Run("Contact.", bold=True), Run(" Smeared on an object.")], [197])],
                   [], Source(197, 197))


class TestGlossary:
    def test_given_the_damage_table_and_poison_section_when_read_then_both_kinds_of_term_are_found(self):
        # Given the glossary's terms, the 13 damage types and one poison type
        # When read
        found = glossary([*terms(), damage_table(*DAMAGE_TYPES), poison()], "SRD.pdf")

        # Then each names its type and the section defining it
        assert [(g["name"], g["term_type"], g["section_id"]) for g in found][-2:] == [
            ("Thunder", "damage type", "11.2.46.1"), ("Contact", "poison type", "12.6")]
        assert found[-1]["description"] == "Smeared on an object."

    def test_given_a_damage_table_missing_a_type_when_read_then_it_is_an_error(self):
        # Given a table of one type
        # When read
        # Then it is refused
        with pytest.raises(ValueError, match="13 damage types"):
            glossary([*terms(), damage_table("Acid"), poison()], "SRD.pdf")

    def test_given_a_condition_missing_from_the_glossary_when_read_then_it_is_an_error(self):
        # Given every term but Prone
        # When read
        # Then the condition list is refused
        with pytest.raises(ValueError, match="condition terms"):
            glossary([*terms("Prone"), damage_table(*DAMAGE_TYPES), poison()], "SRD.pdf")
