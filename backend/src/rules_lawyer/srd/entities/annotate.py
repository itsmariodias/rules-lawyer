"""Each typed section's own record: a spell's fields, a magic item's subtitle, a glossary
term and its tag, a creature group's members."""

from __future__ import annotations

import re

from rules_lawyer.srd.entities.spells import magic_item, spell
from rules_lawyer.srd.model import Section
from rules_lawyer.srd.sections import walk
from rules_lawyer.srd.vocabulary import EntityType, TermType

# A glossary heading's tag: "Prone [Condition]", "Attack [Action]" (41 of 155).
TAGGED = re.compile(r"^(?P<term>.*?)\s*\[(?P<tag>[^\]]+)\]$")


def annotate(sections: list[Section]) -> None:
    """Give each spell, magic item, glossary term and creature group section its record.

    Args:
        sections: The book's sections, typed; annotated in place.
    """
    for section in walk(sections):
        match section.entity_type:
            case EntityType.SPELL:
                section.spell = spell(section)
            case EntityType.MAGIC_ITEM:
                section.item = magic_item(section)
            case EntityType.GLOSSARY_TERM:
                tagged = TAGGED.match(section.heading)
                section.term = tagged.group("term") if tagged else section.heading
                section.term_type = TermType(tagged.group("tag").lower()) if tagged else TermType.DEFINITION
            case EntityType.CREATURE_GROUP:
                section.members = [s.heading for s in walk(section.subsections) if s.entity_type == EntityType.CREATURE]
