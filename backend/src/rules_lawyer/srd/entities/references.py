"""Cross-references: what each section and creature entry mentions, as edges.

Spells and magic items are set in italics, creatures in bold, so an italic or
bold run is a reference when it names one of them (italics also mark emphasis
and book titles, which name nothing). Conditions, actions and damage types
are set plain and match only fixed phrasing ("the Prone condition", "the
Deafened and Frightened conditions", "Fire damage"), and areas of effect only
with a size ("a 20-foot Cone"), so "Cover", "Attack" or "Force" never match as
ordinary words. A captioned table is named by its caption before the word
"table" ("the Barbarian Features table"), capitalised as printed.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from rules_lawyer.srd.entities.mechanics import conditions_imposed
from rules_lawyer.srd.entities.records import named_entries
from rules_lawyer.srd.model import (
    Block,
    Contents,
    ListBlock,
    Paragraph,
    Run,
    Section,
    Sidebar,
    StatBlock,
    Table,
    plain,
)
from rules_lawyer.srd.sections import captioned_tables, walk
from rules_lawyer.srd.vocabulary import (
    Action,
    AreaOfEffect,
    Condition,
    DamageType,
    EntityType,
    StatPart,
    Target,
    alternatives,
)

# A name list: "the Blinded, Deafened, and Poisoned conditions". Every name in it is
# mentioned, or-lists too; whether a condition is imposed is decided elsewhere.
NAME_LIST = re.compile(r",\s+(?:and|or)\s+|,\s+|\s+and\s+|\s+or\s+")
AREA = re.compile(rf"\d+-foot[\w-]*\s+({alternatives(AreaOfEffect)})\b")
IMPOSES_CONDITION = "imposes_condition"


def phrase(vocabulary: type[Condition | Action | DamageType], noun: str) -> re.Pattern:
    """``<name> <noun>``, or a list of names before it ("the Deafened and Frightened conditions")."""
    one = f"(?:{alternatives(vocabulary)})"
    return re.compile(rf"\b({one}(?:(?:,|\s+and|\s+or)\s+{one})*)\s+{noun}s?\b")


def table_phrase(captions: list[str]) -> re.Pattern:
    """``<caption> table`` for any of ``captions``; matches nothing if there are none."""
    # An empty alternation would match the bare word "table" with no caption.
    names = "|".join(re.escape(caption) for caption in sorted(captions, key=len, reverse=True)) or "(?!)"
    return re.compile(rf"\b({names})\s+table\b")


PHRASES = ((Target.CONDITION, phrase(Condition, "condition")), (Target.ACTION, phrase(Action, "action")),
           (Target.DAMAGE_TYPE, phrase(DamageType, "damage")))


class Names:
    """Case-insensitive lookup of a run's text among known names, singular or plural."""

    def __init__(self, names: list[str]) -> None:
        self.by_key = {name.lower(): name for name in names}

    def resolve(self, text: str) -> str | None:
        """The name ``text`` is ("two **Ghasts**" is Ghast), or None."""
        key = text.strip(" .,;:!?’'\"()").lower()
        if key in self.by_key:
            return self.by_key[key]
        for suffix, singular in (("ies", "y"), ("es", ""), ("s", "")):
            if key.endswith(suffix) and (stem := key[:-len(suffix)] + singular) in self.by_key:
                return self.by_key[stem]
        return None


def references(sections: list[Section]) -> list[dict]:
    """Every cross-reference edge: each section's own text, then each creature entry's.

    Args:
        sections: The book's sections, typed and annotated.

    Returns:
        ``{"source", "target", "relation"}`` per edge, each target once per
        source. A creature entry's source names its ``part`` ("actions/Bite").
        A condition the source imposes is ``imposes_condition``; any other
        target ``Target.relation``. A table never references itself.
    """
    tables = table_phrase(list(captioned_tables(sections)))
    spells = Names([s.heading for s in walk(sections) if s.entity_type == EntityType.SPELL])
    items = Names([s.heading for s in walk(sections) if s.entity_type == EntityType.MAGIC_ITEM])
    stat_blocks = [s.blocks[0] for s in walk(sections) if s.entity_type == EntityType.CREATURE]
    creature_names = Names([block.name for block in stat_blocks])

    def edges(source: dict, texts: list[list[Run]], imposed: list[str]) -> list[dict]:
        found: list[tuple[Target, str]] = []
        for runs in texts:
            found += mentions(runs, spells, items, creature_names, tables)
        return [{"source": source, "target": {"type": target, "name": name},
                 "relation": IMPOSES_CONDITION if target == Target.CONDITION and name in imposed else target.relation}
                for target, name in dict.fromkeys(found)
                if not (target == Target.TABLE and name == source["name"])]

    found: list[dict] = []
    for section in walk(sections):
        texts = [runs for block in section.blocks for runs in run_lists(block)]
        imposed = (section.spell or {}).get("conditions_imposed", [])
        found += edges({"type": section.entity_type, "id": section.id, "name": section.heading}, texts, imposed)
    for block in stat_blocks:
        for part in block.sections:
            for name, runs in named_entries(part.entries):
                found += edges({"type": "creature", "name": block.name, "part": f"{StatPart(part.title).field}/{name}"},
                               [runs], conditions_imposed(plain(runs)))
    return found


def mentions(runs: list[Run], spells: Names, items: Names, creatures: Names,
             tables: re.Pattern) -> list[tuple[Target, str]]:
    """What one piece of text names: italic spells and items, bold creatures, then phrases."""
    found: list[tuple[Target, str]] = []
    for run in runs:
        if run.bold:
            if name := creatures.resolve(run.text):
                found.append((Target.CREATURE, name))
        elif run.italic:
            if name := spells.resolve(run.text):
                found.append((Target.SPELL, name))
            elif name := items.resolve(run.text):
                found.append((Target.MAGIC_ITEM, name))
    text = plain(runs)
    for target, pattern in PHRASES:
        found += [(target, name) for match in pattern.finditer(text) for name in NAME_LIST.split(match.group(1))]
    found += [(Target.AREA_OF_EFFECT, match.group(1)) for match in AREA.finditer(text)]
    found += [(Target.TABLE, match.group(1)) for match in tables.finditer(text)]
    return found


def run_lists(block: Block) -> Iterator[list[Run]]:
    """Each piece of text in a block, as runs: a paragraph, a table cell, a stat block field."""
    match block:
        case Paragraph():
            yield block.runs
        case ListBlock():
            for item in block.items:
                for inner in item:
                    yield from run_lists(inner)
        case Sidebar():
            yield block.title
            for inner in block.blocks:
                yield from run_lists(inner)
        case Table():
            yield block.caption
            for row in block.header + block.rows:
                yield from row
        case Contents():
            for entry in block.entries:
                yield entry.runs
        case StatBlock():
            yield block.subtitle
            for field in block.fields:
                yield field.value
            for part in block.sections:
                for entry in part.entries:
                    yield entry.runs


def unresolved(edges: list[dict], sections: list[Section], glossary: list[dict]) -> list[str]:
    """Each edge whose target is not an extracted spell, magic item, creature, glossary term or table.

    Args:
        edges: From ``references``.
        sections: The book's sections, typed.
        glossary: The glossary records.

    Returns:
        "type name" per unresolved target, each once.
    """
    known = {(Target.SPELL, s.heading) for s in walk(sections) if s.entity_type == EntityType.SPELL}
    known |= {(Target.MAGIC_ITEM, s.heading) for s in walk(sections) if s.entity_type == EntityType.MAGIC_ITEM}
    known |= {(Target.CREATURE, s.heading) for s in walk(sections) if s.entity_type == EntityType.CREATURE}
    known |= {(Target.TABLE, caption) for caption in captioned_tables(sections)}
    known |= {(Target(term["term_type"].replace(" ", "_")), term["name"]) for term in glossary
              if term["term_type"].replace(" ", "_") in Target}
    return list(dict.fromkeys(f"{e['target']['type']} {e['target']['name']}" for e in edges
                              if (e["target"]["type"], e["target"]["name"]) not in known))
