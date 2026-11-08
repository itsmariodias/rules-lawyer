from __future__ import annotations

import pytest

from dnd_graph_rag.srd import character


def section(heading: str, content: str = "", node_id: str = "1",
            subsections: list | None = None, **extra) -> dict:
    """A tree node shaped like ``build_tree``'s output."""
    return {
        "id": node_id,
        "heading": heading,
        "content": content,
        "source": {"pdf": "SRD.pdf", "page_start": 1, "page_end": 1,
                   "char_start": 0, "char_end": len(content)},
        "subsections": subsections or [],
        **extra,
    }


class TestParseLabeledFields:
    def test_given_several_labels_on_one_line_when_parsed_then_each_gets_its_value(self):
        # Given the way species, backgrounds and core traits all open
        text = "**Creature Type:** Humanoid **Size:** Medium **Speed:** 30 feet"

        # When the fields are read
        fields = character.parse_labeled_fields(text)

        # Then a value runs up to the next label and no further
        assert fields == {"creature_type": "Humanoid", "size": "Medium",
                          "speed": "30 feet"}

    def test_given_a_multi_word_label_when_parsed_then_the_key_is_snake_cased(self):
        # Given a label of several words
        # When the fields are read
        fields = character.parse_labeled_fields("**Ability Scores:** Dexterity")

        # Then the key is one the graph can carry as a property name
        assert fields == {"ability_scores": "Dexterity"}

    def test_given_a_value_running_into_a_new_paragraph_when_parsed_then_it_stops(self):
        # Given a label whose value is followed by unrelated prose
        text = "**Size:** Medium\n\nThe rest of the entry follows here."

        # When the fields are read
        fields = character.parse_labeled_fields(text)

        # Then the value ends at the paragraph break
        assert fields == {"size": "Medium"}

    def test_given_emphasis_inside_a_value_when_parsed_then_it_is_stripped(self):
        # Given a value carrying the book's own emphasis
        # When the fields are read
        fields = character.parse_labeled_fields("**Size:** _Medium_ or Small")

        # Then the value is the words, not the typography
        assert fields == {"size": "Medium or Small"}

    def test_given_no_labels_at_all_when_parsed_then_nothing_is_found(self):
        # Given ordinary prose
        # When the fields are read
        # Then no fields are invented
        assert character.parse_labeled_fields("Just a paragraph.") == {}


class TestExtractSpecies:
    def test_given_a_species_section_when_extracted_then_its_traits_come_with_it(self):
        # Given a species printed the way the book prints one
        nodes = [section("Species Descriptions", subsections=[
            section("Dwarf", "**Creature Type:** Humanoid **Size:** Medium",
                    node_id="4.1", entries=[
                        {"name": "Darkvision", "description": "120 feet."}])])]

        # When the species are extracted
        species, = character.extract_species(nodes)

        # Then the labelled fields and the named entries both arrive
        assert species["name"] == "Dwarf"
        assert species["kind"] == "species"
        assert species["section_id"] == "4.1"
        assert species["size"] == "Medium"
        assert species["traits"] == [{"name": "Darkvision",
                                      "description": "120 feet."}]

    def test_given_traits_split_by_a_table_when_extracted_then_the_subtree_is_read(self):
        """The Draconic Ancestors table splits the Dragonborn's traits."""
        # Given an entry whose traits continue below a table
        nodes = [section("Species Descriptions", subsections=[
            section("Dragonborn", "**Size:** Medium", node_id="4.2",
                    entries=[{"name": "Draconic Flight", "description": "Wings."}],
                    subsections=[
                        section("Ancestors", "", node_id="4.2.1",
                                entries=[{"name": "Breath Weapon",
                                          "description": "A Cone."}])])])]

        # When the species are extracted
        species, = character.extract_species(nodes)

        # Then traits from below the table are gathered too
        assert [t["name"] for t in species["traits"]] == ["Draconic Flight",
                                                          "Breath Weapon"]

    def test_given_no_species_section_when_extracted_then_nothing_is_returned(self):
        # Given a tree without that heading
        # When the species are extracted
        # Then the answer is empty rather than an error
        assert character.extract_species([section("Classes")]) == []


class TestExtractBackgrounds:
    def test_given_a_background_section_when_extracted_then_it_is_typed_as_one(self):
        # Given a background printed under its own heading
        nodes = [section("Background Descriptions", subsections=[
            section("Acolyte", "**Ability Scores:** Intelligence, Wisdom",
                    node_id="3.1")])]

        # When the backgrounds are extracted
        background, = character.extract_backgrounds(nodes)

        # Then it carries its kind and its labelled fields
        assert background["kind"] == "background"
        assert background["ability_scores"] == "Intelligence, Wisdom"


class TestExtractFeats:
    def test_given_a_feat_when_extracted_then_the_italic_category_wins(self):
        # Given a feat whose printed category differs from its group heading
        nodes = [section("Feat Descriptions", subsections=[
            section("General Feats", subsections=[
                section("Alert", "_Origin Feat_\n\nYou gain Initiative.",
                        node_id="5.1")])])]

        # When the feats are extracted
        feat, = character.extract_feats(nodes)

        # Then the category comes from the feat, and the group is kept beside it
        assert feat["category"] == "Origin Feat"
        assert feat["group"] == "General Feats"

    def test_given_no_printed_category_when_extracted_then_the_group_names_it(self):
        # Given a feat with nothing italicised under its name
        nodes = [section("Feat Descriptions", subsections=[
            section("General Feats", subsections=[
                section("Lucky", "You have luck points.", node_id="5.2")])])]

        # When the feats are extracted
        feat, = character.extract_feats(nodes)

        # Then the group's heading is singularised into a category
        assert feat["category"] == "General Feat"

    def test_given_a_group_that_is_not_feats_when_extracted_then_it_is_skipped(self):
        # Given a sibling section that is not a group of feats
        nodes = [section("Feat Descriptions", subsections=[
            section("Feat Rules", subsections=[
                section("Prerequisites", "You must meet them.", node_id="5.3")])])]

        # When the feats are extracted
        # Then rules prose is not mistaken for a feat
        assert character.extract_feats(nodes) == []


class TestExtractPoisonTypes:
    def test_given_the_introducing_paragraph_when_extracted_then_all_four_are_read(self):
        # Given the passage that defines the whole set
        content = ("Poisons come in the following four types: "
                   "**Contact.** Smeared on an object. "
                   "**Ingested.** Swallowed with food. "
                   "**Inhaled.** A cloud of powder. "
                   "**Injury.** Applied to a weapon.")
        nodes = [section("Poison", content, node_id="12.6")]

        # When the poison types are extracted
        types = character.extract_poison_types(nodes)

        # Then each is a glossary term carrying its own definition
        assert [t["name"] for t in types] == ["Contact", "Ingested", "Inhaled",
                                              "Injury"]
        assert types[0]["term_type"] == "poison type"
        assert types[0]["description"] == "Smeared on an object."
        assert all(t["section_id"] == "12.6" for t in types)

    def test_given_the_book_stops_introducing_them_this_way_when_extracted_then_nothing_is_guessed(self):
        # Given a Poison section without the introducing sentence
        nodes = [section("Poison", "Poisons are dangerous.", node_id="12.6")]

        # When the poison types are extracted
        # Then no labels are invented from the prose that is there
        assert character.extract_poison_types(nodes) == []


class TestExtractPoisons:
    def test_given_a_poison_when_extracted_then_its_price_and_type_are_read(self):
        # Given a poison printed as a heading with prose
        nodes = [section("Sample Poisons", subsections=[
            section("Serpent Venom (200 GP)",
                    "_Injury Poison_\n\nA creature subjected to this poison…",
                    node_id="12.6.5")])]

        # When the poisons are extracted
        poison, = character.extract_poisons(nodes)

        # Then the heading's price and the first line's delivery type are split out
        assert poison["name"] == "Serpent Venom"
        assert poison["cost"] == "200 GP"
        assert poison["cost_gp"] == 200.0
        assert poison["poison_type"] == "Injury"

    def test_given_a_poison_when_extracted_then_it_names_the_section_that_prints_it(self):
        # Given a poison printed under its own heading
        nodes = [section("Sample Poisons", subsections=[
            section("Serpent Venom (200 GP)", "_Injury Poison_\n\nText.",
                    node_id="12.6.5")])]

        # When the poisons are extracted
        poison, = character.extract_poisons(nodes)

        # Then it points back at the section its prose came from
        assert poison["section_id"] == "12.6.5"


class TestExtractDamageTypes:
    def test_given_the_table_when_extracted_then_each_type_is_a_glossary_term(self):
        # Given the Damage Types table
        content = ("| Type | Examples |\n|---|---|\n"
                   "| Fire | A red dragon's breath |\n"
                   "| Cold | An ice devil's spear |")
        nodes = [section("Damage Types", content, node_id="11.2.46.1")]

        # When the damage types are extracted
        types = character.extract_damage_types(nodes)

        # Then each row becomes a term, sharing the one section that prints them
        assert [t["name"] for t in types] == ["Fire", "Cold"]
        assert types[0]["term_type"] == "damage type"
        assert {t["section_id"] for t in types} == {"11.2.46.1"}

    def test_given_the_table_printed_in_two_halves_when_extracted_then_none_repeats(self):
        """The book prints the table in two side-by-side halves."""
        # Given the same type appearing in both halves
        content = ("| Type | Examples |\n|---|---|\n| Fire | Dragon |\n\n"
                   "| Type | Examples |\n|---|---|\n| Fire | Dragon |\n"
                   "| Cold | Devil |")
        nodes = [section("Damage Types", content, node_id="11.2.46.1")]

        # When the damage types are extracted
        types = character.extract_damage_types(nodes)

        # Then each type appears exactly once
        assert [t["name"] for t in types] == ["Fire", "Cold"]
