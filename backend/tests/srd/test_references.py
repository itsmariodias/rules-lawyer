"""
The cross-reference edges, and the name resolution behind them.

Edges come from the book's own markup — spells and magic items italicised,
creatures bolded — but a span only becomes an edge when it resolves to an
entity that was actually extracted, since italic is also emphasis and book
titles.  Conditions, actions and damage types are not marked up at all, so
they match on required phrasing.
"""

from __future__ import annotations

import pytest

from dnd_graph_rag.srd import references
from dnd_graph_rag.srd.references import NameIndex, ReferenceScanner


def glossary(*entries: tuple[str, str]) -> list[dict]:
    """Glossary records, as ``(name, term_type)`` pairs."""
    return [{"name": name, "term_type": term_type, "description": "",
             "section_id": "11.2"} for name, term_type in entries]


@pytest.fixture
def scanner() -> ReferenceScanner:
    """A scanner over a small, closed set of known entities."""
    return ReferenceScanner(
        spells=["Fireball", "Cure Wounds"],
        magic_items=["Bag of Holding"],
        creatures=["Goblin", "Ghast", "Harpy"],
        glossary=glossary(("Prone", "condition"), ("Charmed", "condition"),
                          ("Utilize", "action"), ("Fire", "damage type"),
                          ("Force", "damage type"), ("Cone", "area of effect")),
    )


class TestNormalise:
    """A captured span, reduced to the name inside it."""

    def test_given_emphasis_when_normalised_then_only_the_name_is_left(self):
        # Given a span carrying the markup it was captured with
        # When it is normalised
        # Then the markers are gone
        assert references.normalise("**Goblin**") == "Goblin"

    def test_given_trailing_punctuation_when_normalised_then_it_is_dropped(self):
        # Given a name that ended a sentence
        # When it is normalised
        # Then the sentence's punctuation is not part of the name
        assert references.normalise("_Fireball._") == "Fireball"


class TestNameIndex:
    """Resolving a captured span to a known entity name."""

    def test_given_an_exact_name_when_resolved_then_it_comes_back_as_printed(self):
        # Given an index of known creatures
        index = NameIndex(["Goblin"])

        # When a span naming one is resolved
        # Then the canonical spelling is returned
        assert index.resolve("Goblin") == "Goblin"

    def test_given_a_different_case_when_resolved_then_it_still_matches(self):
        """A few references appear mid-sentence in lower case."""
        # Given an index of known creatures
        index = NameIndex(["Goblin"])

        # When a lower-case span is resolved
        # Then case is not what tells two entities apart
        assert index.resolve("goblin") == "Goblin"

    @pytest.mark.parametrize("plural,singular", [
        ("Ghasts", "Ghast"), ("Harpies", "Harpy"), ("Boxes", "Box"),
    ])
    def test_given_a_plural_when_resolved_then_it_falls_back_to_the_singular(
            self, plural, singular):
        """The book pluralises references freely: "two **Ghasts**"."""
        # Given an index holding the singular
        index = NameIndex([singular])

        # When the plural is resolved
        # Then it finds the entity it names
        assert index.resolve(plural) == singular

    def test_given_an_unknown_span_when_resolved_then_nothing_is_invented(self):
        # Given an index that does not hold the name
        index = NameIndex(["Goblin"])

        # When an unknown span is resolved
        # Then no entity is invented for it
        assert index.resolve("Displacer Beast") is None

    def test_given_an_empty_span_when_resolved_then_nothing_comes_back(self):
        # Given an index
        index = NameIndex(["Goblin"])

        # When an empty span is resolved
        # Then the absence is answered rather than matched
        assert index.resolve("  ") is None


class TestReferenceScannerScan:
    """Every resolvable cross-reference in a piece of SRD text."""

    def test_given_an_italicised_spell_when_scanned_then_it_is_a_spell_reference(self):
        # Given the book's own markup for a spell
        # When the text is scanned
        found = ReferenceScanner(["Fireball"], [], [], []).scan(
            "The creature casts _Fireball_.")

        # Then it resolves to the spell
        assert found == [("spell", "Fireball")]

    def test_given_a_bolded_creature_when_scanned_then_it_is_a_creature_reference(
            self, scanner):
        # Given the book's own markup for a creature
        # When the text is scanned
        found = scanner.scan("It summons two **Ghasts**.")

        # Then it resolves through the plural to the stat block
        assert ("creature", "Ghast") in found

    def test_given_italic_that_is_only_emphasis_when_scanned_then_no_edge_is_drawn(
            self, scanner):
        """Italic is also emphasis and book titles, so resolution is the filter."""
        # Given an italicised phrase that names no entity
        # When the text is scanned
        found = scanner.scan("The creature is _truly_ dangerous.")

        # Then nothing was drawn from the typography alone
        assert found == []

    def test_given_the_required_phrasing_when_scanned_then_a_condition_matches(
            self, scanner):
        # Given a condition named the way the book names one
        # When the text is scanned
        found = scanner.scan("The target has the Prone condition.")

        # Then the condition is picked up without any markup
        assert found == [("condition", "Prone")]

    def test_given_a_bare_noun_when_scanned_then_it_does_not_fire(self, scanner):
        """"Cover", "Attack" and "Force" would all fire as bare nouns."""
        # Given the word used as an ordinary noun
        # When the text is scanned
        found = scanner.scan("The creature is pushed with great Force.")

        # Then the required phrasing is what stops it
        assert found == []

    def test_given_a_damage_type_when_scanned_then_it_needs_the_word_damage(
            self, scanner):
        # Given a damage type named as the book names one
        # When the text is scanned
        found = scanner.scan("The target takes 8d6 Fire damage.")

        # Then it resolves to the damage type
        assert found == [("damage_type", "Fire")]

    def test_given_an_action_when_scanned_then_it_needs_the_word_action(self, scanner):
        # Given an action named as the book names one
        # When the text is scanned
        found = scanner.scan("You take the Utilize action.")

        # Then it resolves to the action
        assert found == [("action", "Utilize")]

    def test_given_a_sized_area_when_scanned_then_the_shape_is_captured(self):
        """Areas of effect are always sized: "a 60-foot Cone"."""
        # Given an area printed the way the book prints one
        # When the text is scanned
        found = ReferenceScanner([], [], [], []).scan(
            "Each creature in a 60-foot Cone must save.")

        # Then the shape is picked up
        assert found == [("area_of_effect", "Cone")]

    def test_given_the_same_reference_twice_when_scanned_then_it_appears_once(
            self, scanner):
        # Given text naming one spell twice
        # When it is scanned
        found = ReferenceScanner(["Fireball"], [], [], []).scan(
            "It casts _Fireball_ and then _Fireball_ again.")

        # Then the pairs are deduplicated, in a stable order
        assert found == [("spell", "Fireball")]

    def test_given_a_term_type_with_no_dependable_phrasing_when_built_then_it_is_not_matched(self):
        """Only conditions, actions, areas and damage types have one."""
        # Given a glossary holding a plain definition
        scanner = ReferenceScanner([], [], [], glossary(("Ability Check",
                                                          "definition")))

        # When text naming it is scanned
        found = scanner.scan("Make an Ability Check to climb.")

        # Then no edge is drawn from a phrase that cannot be matched reliably
        assert found == []


class TestEdges:
    """One piece of text, turned into edges."""

    def test_given_a_condition_that_is_inflicted_when_built_then_the_relation_is_stronger(
            self, scanner):
        """
        Typography only says two things are mentioned together; the direction
        comes from ``mechanics``, and is passed in.
        """
        # Given text imposing a condition, and the caller's own determination
        text = "The target has the Prone condition."
        source = {"type": "creature", "name": "Goblin", "part": "actions/Bite"}

        # When the edges are built with that condition marked as imposed
        edges = references._edges(scanner, text, source, imposed=["Prone"])

        # Then the edge says it inflicts rather than mentions
        assert edges == [{"source": source,
                          "target": {"type": "condition", "name": "Prone"},
                          "relation": "imposes_condition"}]

    def test_given_a_condition_only_mentioned_when_built_then_it_stays_a_mention(
            self, scanner):
        # Given the same text with nothing marked as imposed
        text = "The target has the Prone condition."
        source = {"type": "rule", "id": "1", "name": "Prone"}

        # When the edges are built
        edges = references._edges(scanner, text, source)

        # Then the weaker relation is used
        assert edges[0]["relation"] == "references_condition"

    def test_given_empty_text_when_built_then_there_are_no_edges(self, scanner):
        # Given a section with no prose
        # When the edges are built
        # Then nothing is drawn from nothing
        assert references._edges(scanner, "", {"type": "rule"}) == []


class TestMarkGlossaryNodes:
    """Flagging the children of "Rules Definitions" so they read as terms."""

    def test_given_the_glossary_section_when_marked_then_its_children_are_flagged(self):
        # Given the section the glossary lives under
        nodes = [{"heading": "Rules Definitions", "subsections": [
            {"heading": "Prone [Condition]"}]}]

        # When the glossary nodes are marked
        references.mark_glossary_nodes(nodes)

        # Then each child is flagged for the extractor that follows
        assert nodes[0]["subsections"][0]["_is_glossary"] is True

    def test_given_any_other_section_when_marked_then_nothing_is_flagged(self):
        # Given a section that is not the glossary
        nodes = [{"heading": "Spells", "subsections": [{"heading": "Fireball"}]}]

        # When the glossary nodes are marked
        references.mark_glossary_nodes(nodes)

        # Then nothing outside the glossary is treated as a term
        assert "_is_glossary" not in nodes[0]["subsections"][0]


class TestExtractGlossary:
    """The Rules Glossary, read into typed term records."""

    def test_given_a_tagged_entry_when_extracted_then_the_book_does_the_typing(self):
        """A condition is a condition because the SRD bracketed it as one."""
        # Given a flagged glossary entry carrying the book's own tag
        node = {"id": "11.2.114", "heading": "Prone [Condition]",
                "content": "While you have the Prone condition…",
                "source": {"pdf": "SRD.pdf", "page_start": 372, "page_end": 372},
                "_is_glossary": True}

        # When the glossary is extracted
        term, = references.extract_glossary([node])

        # Then the term and its type come from the heading
        assert term["name"] == "Prone"
        assert term["term_type"] == "condition"
        assert term["section_id"] == "11.2.114"

    def test_given_a_tagged_entry_when_extracted_then_the_node_is_typed_too(self):
        # Given the same entry
        node = {"id": "11.2.114", "heading": "Prone [Condition]", "content": "",
                "source": {"pdf": "SRD.pdf", "page_start": 372, "page_end": 372},
                "_is_glossary": True}

        # When the glossary is extracted
        references.extract_glossary([node])

        # Then the section itself now says what it is
        assert node["entity_type"] == "glossary_term"
        assert node["term"] == "Prone"

    def test_given_an_untagged_entry_when_extracted_then_it_is_a_plain_definition(self):
        # Given an entry the book did not bracket
        node = {"id": "11.2.1", "heading": "Ability Check", "content": "A roll.",
                "source": {"pdf": "SRD.pdf", "page_start": 360, "page_end": 360},
                "_is_glossary": True}

        # When the glossary is extracted
        term, = references.extract_glossary([node])

        # Then it is typed as a definition rather than guessed at
        assert term["term_type"] == "definition"

    def test_given_an_unflagged_node_when_extracted_then_it_is_not_a_term(self):
        # Given a section outside the glossary
        node = {"id": "5", "heading": "Fireball", "content": "",
                "source": {"pdf": "SRD.pdf", "page_start": 1, "page_end": 1}}

        # When the glossary is extracted
        # Then nothing outside "Rules Definitions" becomes a term
        assert references.extract_glossary([node]) == []
