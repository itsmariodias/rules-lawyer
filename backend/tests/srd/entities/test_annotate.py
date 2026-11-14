from __future__ import annotations

from rules_lawyer.srd.entities.annotate import annotate
from rules_lawyer.srd.model import Section, Source, StatBlock


def section(id: str, heading: str, entity_type: str, *subsections: Section) -> Section:
    return Section(id, heading, 4, [], list(subsections), Source(1, 1), entity_type)


class TestAnnotate:
    def test_given_glossary_headings_when_annotated_then_a_tag_is_the_terms_type(self):
        # Given a tagged and an untagged definition
        sections = [section("1", "Prone [Condition]", "glossary_term"), section("2", "Advantage", "glossary_term")]

        # When annotated
        annotate(sections)

        # Then the tag is lowercased into the type, and no tag is a definition
        assert [(s.term, s.term_type) for s in sections] == [("Prone", "condition"), ("Advantage", "definition")]

    def test_given_a_creature_group_when_annotated_then_its_creatures_are_its_members_in_book_order(self):
        # Given the Black Dragons entry over two of its stat blocks
        wyrmling = Section("15.13.1", "Black Dragon Wyrmling", 3,
                           [StatBlock("Black Dragon Wyrmling", [], [], [], [], [263])], [], Source(263, 263), "creature")
        adult = Section("15.13.2", "Adult Black Dragon", 3,
                        [StatBlock("Adult Black Dragon", [], [], [], [], [264])], [], Source(264, 264), "creature")
        group = section("15.13", "Black Dragons", "creature_group", wyrmling, adult)

        # When annotated
        annotate([group])

        # Then its members are the stat blocks under it, as printed
        assert group.members == ["Black Dragon Wyrmling", "Adult Black Dragon"]
