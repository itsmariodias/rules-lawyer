"""Section types from what the book prints, never from where a section sits.

A section is ``rule`` unless evidence says otherwise: from its blocks
(``type_sections``) a spell's or magic item's italic subtitle, a stat block, a
monster entry over stat blocks, a glossary definition, an entry of a closed
set, the front matter; from the records read later (``type_from_records``)
being a class, subclass, feature, species, background, feat or item.
"""

from __future__ import annotations

import re

from rules_lawyer.srd.model import Paragraph, Section, StatBlock, plain
from rules_lawyer.srd.sections import walk
from rules_lawyer.srd.vocabulary import EntityType

# "Level 2 Evocation (Wizard)", "Evocation Cantrip (Sorcerer, Wizard)": 339.
SPELL_SUBTITLE = re.compile(r"^(?:Level \d \w+|\w+ Cantrip) \([^)]*\)$")
# "Wondrous Item, Rare (Requires Attunement)", "Weapon (Any Sword), Very Rare": 258.
ITEM_SUBTITLE = re.compile(r"^(?:Armor|Potion|Ring|Rod|Scroll|Staff|Wand|Weapon|Wondrous Item)\b")
# The chapters of monster entries; an entry there over stat blocks is a group (177).
MONSTER_CHAPTERS = ("Monsters A–Z", "Animals")
# Each subsection of this heading is a glossary definition (155).
GLOSSARY = "Rules Definitions"
# Closed sets: each entry of the heading is one of the type. Its entries are its
# subsections, or the sections after it at its level when it has none
# ("Example Contagions" heads nothing; Cackle Fever, Sewer Plague and Sight
# Rot follow it).
ENTRY_SETS = {"Environmental Effects": EntityType.ENVIRONMENTAL_EFFECT, "Example Traps": EntityType.TRAP,
              "Example Contagions": EntityType.CONTAGION, "Metamagic Options": EntityType.CLASS_FEATURE,
              "Eldritch Invocation Options": EntityType.CLASS_FEATURE}
# Pages 1 to 4: the legal notice, the Contents and the Index of Stat Blocks.
FRONT_MATTER_END = 4


def type_sections(sections: list[Section]) -> None:
    """Give each section the type its blocks show, ``rule`` by default.

    Args:
        sections: The book's top-level sections, typed in place.
    """
    for root in sections:
        if root.source.page_end <= FRONT_MATTER_END:
            root.entity_type = EntityType.FRONT_MATTER
        type_children(root, in_monster_chapter=root.heading in MONSTER_CHAPTERS)


def type_children(parent: Section, in_monster_chapter: bool) -> None:
    """Type ``parent``'s subsections, and theirs, from their blocks and the sets they are in."""
    set_type = ENTRY_SETS.get(parent.heading)
    for position, section in enumerate(parent.subsections):
        if subtitle := italic_subtitle(section):
            if SPELL_SUBTITLE.match(subtitle):
                section.entity_type = EntityType.SPELL
            elif ITEM_SUBTITLE.match(subtitle):
                section.entity_type = EntityType.MAGIC_ITEM
        if len(section.blocks) == 1 and isinstance(section.blocks[0], StatBlock):
            section.entity_type = EntityType.CREATURE
        elif in_monster_chapter and any(len(c.blocks) == 1 and isinstance(c.blocks[0], StatBlock)
                                        for c in section.subsections):
            section.entity_type = EntityType.CREATURE_GROUP
        if parent.heading == GLOSSARY:
            section.entity_type = EntityType.GLOSSARY_TERM
        if set_type:
            section.entity_type = set_type
        elif section.heading in ENTRY_SETS and not section.subsections:
            for entry in parent.subsections[position + 1:]:
                entry.entity_type = ENTRY_SETS[section.heading]
        type_children(section, in_monster_chapter)


def type_from_records(sections: list[Section], classes: list[dict], origins: list[dict],
                      feats: list[dict], equipment: list[dict]) -> None:
    """Type each section a record names as that record's kind.

    The records are found by the book's own structure (a class's "Level N:"
    features, a feat under its category heading), so they are evidence
    independent of where a section sits. Only ``rule`` sections are retyped: a
    subtitle or stat block has already said what the rest are.

    Args:
        sections: The book's sections, typed in place.
        classes: Class records: the class and subclass sections become
            ``class`` and ``subclass``, their features ``class_feature``.
        origins: Species and background records: ``origin``.
        feats: Feat records: ``feat``.
        equipment: Item records naming a section (gear, poisons): ``equipment``.
    """
    by_id = {section.id: section for section in walk(sections)}
    named: list[tuple[str, EntityType]] = []
    for record in classes:
        named.append((record["section_id"], EntityType.CLASS))
        named += [(subclass["section_id"], EntityType.SUBCLASS) for subclass in record["subclasses"]]
        named += [(feature["section_id"], EntityType.CLASS_FEATURE) for feature in record["features"]]
    named += [(record["section_id"], EntityType.ORIGIN) for record in origins]
    named += [(record["section_id"], EntityType.FEAT) for record in feats]
    named += [(record["section_id"], EntityType.EQUIPMENT) for record in equipment if "section_id" in record]
    for section_id, entity_type in named:
        if by_id[section_id].entity_type == EntityType.RULE:
            by_id[section_id].entity_type = entity_type


def italic_subtitle(section: Section) -> str | None:
    """The text of the section's first block if it is an italic line, as under a spell's heading."""
    first = section.blocks[0] if section.blocks else None
    if isinstance(first, Paragraph) and all(run.italic for run in first.runs):
        return plain(first.runs)
    return None
