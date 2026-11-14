"""Spell and magic item fields, from the subtitle under the heading and the fields after it."""

from __future__ import annotations

import re

from dnd_graph_rag.srd.entities.mechanics import spell_mechanics
from dnd_graph_rag.srd.model import ListBlock, Paragraph, Section, plain
from dnd_graph_rag.srd.vocabulary import Rarity, alternatives

# "Level 2 Evocation (Wizard)", "Evocation Cantrip (Sorcerer, Wizard)".
SPELL_SUBTITLE = re.compile(r"^(?:Level (\d+) (\w+)|(\w+) Cantrip)(?: \(([^)]+)\))?")
# A spell's fields, each a paragraph led by its bold label; the book writes
# "Component:" as well as "Components:" (12 spells).
SPELL_FIELDS = {"Casting Time": "casting_time", "Range": "range", "Components": "components",
                "Component": "components", "Duration": "duration"}
MATERIAL = re.compile(r"M\s*\(([^)]*)\)", re.IGNORECASE)
# Usually "worth 100+ GP"; Create Undead has "one 150+ GP black onyx stone".
MATERIAL_COST = re.compile(r"(?:worth\s+)?([\d,]+)\+?\s*GP", re.IGNORECASE)
RARITY = re.compile(rf"\b({alternatives(Rarity)})\b")
ATTUNEMENT = re.compile(r"\(Requires Attunement(?:\s+by\s+([^)]+))?\)", re.IGNORECASE)


def spell(section: Section) -> dict:
    """A spell's level, school and classes, its four fields, and what its text does.

    Args:
        section: A section typed ``spell``: its subtitle first, its fields after.

    Returns:
        ``level`` (0 for a cantrip), ``school``, ``classes``, ``ritual``,
        ``casting_time``, ``range``, ``components`` (with ``components_printed``),
        ``concentration``, ``duration``, and ``spell_mechanics``'s fields.
    """
    found = SPELL_SUBTITLE.match(plain(section.blocks[0].runs))
    record: dict = {"level": int(found.group(1) or 0), "school": found.group(2) or found.group(3),
                    "classes": [c.strip() for c in found.group(4).split(",")] if found.group(4) else []}
    fields: dict[str, str] = {}
    for block in section.blocks[1:]:
        if isinstance(block, Paragraph) and block.runs[0].bold:
            label = block.runs[0].text.strip().rstrip(":")
            if label in SPELL_FIELDS:
                fields.setdefault(SPELL_FIELDS[label], " ".join(plain(block.runs[1:]).split()))
    if casting_time := fields.get("casting_time"):
        record["ritual"] = bool(re.search(r"\bor Ritual\b", casting_time, re.IGNORECASE))
        record["casting_time"] = re.sub(r"\s*or Ritual\b", "", casting_time, flags=re.IGNORECASE).strip()
    if "range" in fields:
        record["range"] = fields["range"]
    if printed := fields.get("components"):
        record["components"] = components(printed)
        record["components_printed"] = printed
    if duration := fields.get("duration"):
        record["concentration"] = duration.lower().startswith("concentration")
        record["duration"] = re.sub(r"^Concentration,\s*", "", duration, flags=re.IGNORECASE).strip()
    return record | spell_mechanics(" ".join(text_of(block) for block in section.blocks))


def components(printed: str) -> dict:
    """"V, S, M (a diamond worth 300+ GP, which the spell consumes)" read into parts."""
    letters = {part.strip().upper() for part in printed.split("(")[0].split(",")}
    material = MATERIAL.search(printed)
    found: dict = {"verbal": "V" in letters, "somatic": "S" in letters,
                   "material": material.group(1).strip() if material else None}
    if material:
        cost = MATERIAL_COST.search(material.group(1))
        found["material_cost_gp"] = int(cost.group(1).replace(",", "")) if cost else None
        found["material_consumed"] = bool(re.search(r"consume", material.group(1), re.IGNORECASE))
    return found


def magic_item(section: Section) -> dict:
    """A magic item's category, subtype, rarity and attunement, from its subtitle
    ("Weapon (Any Sword), Rare (Requires Attunement)")."""
    text = plain(section.blocks[0].runs).strip()
    requirement = None
    if attunement := ATTUNEMENT.search(text):
        requirement = attunement.group(1).strip() if attunement.group(1) else None
        text = (text[:attunement.start()] + text[attunement.end():]).strip().rstrip(",")
    parts = re.match(r"^([A-Za-z ]+?)(?:\s*\(([^)]+)\))?(?:,\s*(.*))?$", text)
    rest = parts.group(3) or text
    return {"category": parts.group(1).strip(), "subtype": parts.group(2).strip() if parts.group(2) else None,
            "rarity": Rarity(rarity.group(1)) if (rarity := RARITY.search(rest)) else None,
            "requires_attunement": attunement is not None, "attunement_requirement": requirement}


def text_of(block: object) -> str:
    """A paragraph's or list's text, styles dropped; other blocks have none here."""
    if isinstance(block, Paragraph):
        return plain(block.runs)
    if isinstance(block, ListBlock):
        return " ".join(text_of(b) for item in block.items for b in item)
    return ""
