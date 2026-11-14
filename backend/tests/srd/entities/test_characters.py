from __future__ import annotations

from rules_lawyer.srd.entities.characters import column_labels, progression
from rules_lawyer.srd.model import Run, Table


def cells(*texts: str) -> list[list[Run]]:
    return [[Run(text)] if text else [] for text in texts]


# Page 31's Bard Features: two header rows, the spell slot label printed once over 1.
BARD = Table([Run("Bard Features", bold=True)],
             [cells("", "Proficiency", "", "Bardic", "\u2014Spell Slots per Spell Level\u2014", "", ""),
              cells("Level", "Bonus", "Class Features", "Die", "1", "2", "3")],
             [cells("1", "+2", "Bardic Inspiration, Spellcasting", "D6", "2", "\u2014", "\u2014"),
              cells("11", "+4", "\u2014", "D10", "4", "3", "3")], [31])


class TestColumnLabels:
    def test_given_two_header_rows_when_labelled_then_each_column_joins_them_and_slots_take_the_span(self):
        # Given the Bard Features header
        # When labelled
        # Then a wrapped label is joined, and each slot level takes the label spanning it
        assert column_labels(BARD) == ["Level", "Proficiency Bonus", "Class Features", "Bardic Die",
                                       "Spell Slots per Spell Level 1", "Spell Slots per Spell Level 2",
                                       "Spell Slots per Spell Level 3"]


class TestProgression:
    def test_given_the_features_table_when_read_then_each_level_has_its_bonus_features_and_resources(self):
        # Given the Bard Features rows for levels 1 and 11
        level_1, level_11 = progression(BARD)

        # When read
        # Then the bonus and features are fields, other columns resources, and "\u2014" no feature
        assert level_1 == {"level": 1, "proficiency_bonus": 2, "features": ["Bardic Inspiration", "Spellcasting"],
                           "resources": {"Bardic Die": "D6", "Spell Slots per Spell Level 1": "2",
                                         "Spell Slots per Spell Level 2": "\u2014",
                                         "Spell Slots per Spell Level 3": "\u2014"}}
        assert level_11["features"] == []
