"""Section types from what the book prints, never from where a section sits.

A section is ``rule`` unless its blocks show otherwise: a spell's or magic
item's italic subtitle, a stat block, a monster entry over stat blocks, a
glossary definition, an entry of a closed set, the front matter. The types
read from entity records (class, subclass, class_feature, origin, feat,
equipment) are stage 3's.
"""

from __future__ import annotations

import re

from .model import Paragraph, Section, StatBlock, plain

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
ENTRY_SETS = {"Environmental Effects": "environmental_effect", "Example Traps": "trap",
              "Example Contagions": "contagion"}
# Pages 1 to 4: the legal notice, the Contents and the Index of Stat Blocks.
FRONT_MATTER_END = 4


def type_sections(sections: list[Section]) -> None:
    """Give each section the type its blocks show, ``rule`` by default.

    Args:
        sections: The book's top-level sections, typed in place.
    """
    for root in sections:
        if root.source.page_end <= FRONT_MATTER_END:
            root.entity_type = "front_matter"
        type_children(root, in_monster_chapter=root.heading in MONSTER_CHAPTERS)


def type_children(parent: Section, in_monster_chapter: bool) -> None:
    """Type ``parent``'s subsections, and theirs, from their blocks and the sets they are in."""
    set_type = ENTRY_SETS.get(parent.heading)
    for position, section in enumerate(parent.subsections):
        if subtitle := italic_subtitle(section):
            if SPELL_SUBTITLE.match(subtitle):
                section.entity_type = "spell"
            elif ITEM_SUBTITLE.match(subtitle):
                section.entity_type = "magic_item"
        if len(section.blocks) == 1 and isinstance(section.blocks[0], StatBlock):
            section.entity_type = "creature"
        elif in_monster_chapter and any(len(c.blocks) == 1 and isinstance(c.blocks[0], StatBlock)
                                        for c in section.subsections):
            section.entity_type = "creature_group"
        if parent.heading == GLOSSARY:
            section.entity_type = "glossary_term"
        if set_type:
            section.entity_type = set_type
        elif section.heading in ENTRY_SETS and not section.subsections:
            for entry in parent.subsections[position + 1:]:
                entry.entity_type = ENTRY_SETS[section.heading]
        type_children(section, in_monster_chapter)


def italic_subtitle(section: Section) -> str | None:
    """The text of the section's first block if it is an italic line, as under a spell's heading."""
    first = section.blocks[0] if section.blocks else None
    if isinstance(first, Paragraph) and all(run.italic for run in first.runs):
        return plain(first.runs)
    return None
