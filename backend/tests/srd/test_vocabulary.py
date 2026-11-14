from __future__ import annotations

import json

from dnd_graph_rag.srd.vocabulary import (
    Coin,
    Condition,
    EntityType,
    Rarity,
    StatPart,
    alternatives,
)


class TestVocabulary:
    def test_given_members_when_written_then_they_are_the_books_strings(self):
        # Given an entity type and a condition
        # When written to JSON and compared with printed text
        # Then each is its own string
        assert json.dumps([EntityType.CLASS_FEATURE, Condition.PRONE]) == '["class_feature", "Prone"]'
        assert "Frightened" in Condition and "Bludgeoning" not in Condition

    def test_given_coins_and_stat_parts_when_asked_then_they_give_value_and_field(self):
        # Given copper and Bonus Actions
        # When asked for their gold value and record field
        # Then each answers from the book
        assert (Coin.CP.in_gold, StatPart.BONUS_ACTIONS.field) == (0.01, "bonus_actions")


class TestAlternatives:
    def test_given_overlapping_values_when_alternated_then_the_longer_comes_first(self):
        # Given rarities where "Rare" is inside "Very Rare"
        found = alternatives(Rarity).split("|")

        # When alternated
        # Then a regex tries the longer first
        assert found.index("Very Rare") < found.index("Rare")
        assert found.index("Uncommon") < found.index("Common")
