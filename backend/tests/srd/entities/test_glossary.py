from __future__ import annotations

import pytest

from dnd_graph_rag.srd.entities.glossary import glossary
from dnd_graph_rag.srd.model import Paragraph, Run, Section, Source, Table


def damage_table(*names: str) -> Section:
    table = Table([Run("Damage Types", bold=True)], [], [[[Run(name)], [Run("Examples")]] for name in names], [180])
    return Section("11.2.46.1", "Damage Types", 5, [table], [], Source(180, 180))


def poison() -> Section:
    return Section("12.6", "Poison", 2, [Paragraph([Run("Poisons come in the following four types:")], [197]),
                                         Paragraph([Run("Contact.", bold=True), Run(" Smeared on an object.")], [197])],
                   [], Source(197, 197))


class TestGlossary:
    def test_given_the_damage_table_and_poison_section_when_read_then_both_kinds_of_term_are_found(self):
        # Given the 13 damage types and one poison type
        names = ["Acid", "Bludgeoning", "Cold", "Fire", "Force", "Lightning", "Necrotic", "Piercing", "Poison",
                 "Psychic", "Radiant", "Slashing", "Thunder"]

        # When read
        found = glossary([damage_table(*names), poison()], "SRD.pdf")

        # Then each names its type and the section defining it
        assert [(g["name"], g["term_type"], g["section_id"]) for g in found][-2:] == [
            ("Thunder", "damage type", "11.2.46.1"), ("Contact", "poison type", "12.6")]
        assert found[-1]["description"] == "Smeared on an object."

    def test_given_a_damage_table_missing_a_type_when_read_then_it_is_an_error(self):
        # Given a table of one type
        # When read
        # Then it is refused
        with pytest.raises(ValueError, match="13 damage types"):
            glossary([damage_table("Acid"), poison()], "SRD.pdf")
