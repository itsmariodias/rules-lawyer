"""Weapons, armour, adventuring gear and poisons as item records.

Weapons and armour are only table rows, each under a category row ("Simple
Melee Weapons", "Light Armor (...)"). Gear and poisons are sections headed with
their price ("Acid (25 GP)"); gear also has a row in the Adventuring Gear
table, for its weight.
"""

from __future__ import annotations

import re

from rules_lawyer.srd.entities.records import source
from rules_lawyer.srd.model import Paragraph, Section, Table, plain
from rules_lawyer.srd.output.render import section_text
from rules_lawyer.srd.sections import walk
from rules_lawyer.srd.vocabulary import Coin, ItemKind, alternatives

COST = re.compile(rf"([\d,]+)\s*({alternatives(Coin)})\b", re.IGNORECASE)
# The book's weights use vulgar fractions ("1½ lb.").
FRACTIONS = {"¼": 0.25, "½": 0.5, "¾": 0.75}
WEIGHT = re.compile(r"([\d,]*)\s*([¼½¾])?\s*lb", re.IGNORECASE)
# Every weapon rolls dice but the Blowgun, which deals a flat 1 Piercing.
WEAPON_DAMAGE = re.compile(r"^(\d+d\d+|\d+)\s+(\w+)$")
# A property may hold commas in its parentheses ("Ammunition (Range 80/320; Bolt)").
PROPERTY = re.compile(r"[^,(]+(?:\([^)]*\))?")
PRICED = re.compile(r"^(.*?)\s*\(([^)]*)\)\s*$")


def equipment(sections: list[Section], pdf: str) -> list[dict]:
    """Every weapon, armour, gear and poison record, in that order.

    Args:
        sections: The book's sections.
        pdf: The PDF's file name, recorded in each record's ``source``.

    Returns:
        One record per item; gear and poisons name the ``section_id`` they
        are described in, weapons and armour the ``table_id`` printing them.
    """
    # "Adventuring Gear" heads both the gear's section and its table's.
    described = next(s for s in walk(sections) if s.heading == "Adventuring Gear" and not is_table(s, s.heading))
    return (weapons(table_section(sections, "Weapons"), pdf) + armor(table_section(sections, "Armor"), pdf)
            + gear(described, table_section(sections, "Adventuring Gear"), pdf)
            + poisons(next(s for s in walk(sections) if s.heading == "Sample Poisons"), pdf))


def weapons(section: Section, pdf: str) -> list[dict]:
    """The Weapons table's rows, each with the category it is printed under."""
    table: Table = section.blocks[0]
    records = []
    for row, category in rows_by_category(table):
        name, damage_cell, properties, mastery, weight, cost = (plain(cell).strip() for cell in row)
        damage = WEAPON_DAMAGE.match(damage_cell)
        records.append({"name": name, "kind": ItemKind.WEAPON, "category": re.sub(r"\s*Weapons$", "", category),
                        "damage": {"dice": damage.group(1), "type": damage.group(2)} if damage else None,
                        "properties": [] if properties in ("", "\u2014") else
                        [p.strip() for p in PROPERTY.findall(properties) if p.strip()],
                        "mastery": mastery or None, "weight_lb": weight_lb(weight), **price(cost),
                        "table_id": section.id, "source": source(section, pdf)})
    return records


def armor(section: Section, pdf: str) -> list[dict]:
    """The Armor table's rows, the Shield among them."""
    table: Table = section.blocks[0]
    records = []
    for row, category in rows_by_category(table):
        name, armor_class, strength, stealth, weight, cost = (plain(cell).strip() for cell in row)
        required = re.search(r"\d+", strength)
        records.append({"name": name, "kind": ItemKind.ARMOR,
                        # "Light Armor (1 Minute to Don or Doff)" -> "Light"
                        "category": re.split(r"\s+Armor\b|\s*\(", category)[0].strip(),
                        "armor_class": armor_class or None,
                        "strength_requirement": int(required.group()) if required else None,
                        "stealth_disadvantage": "disadvantage" in stealth.lower(),
                        "weight_lb": weight_lb(weight), **price(cost), "table_id": section.id,
                        "source": source(section, pdf)})
    return records


def gear(parent: Section, table_section: Section, pdf: str) -> list[dict]:
    """Each item described under Adventuring Gear, with its table row's weight and price.

    An item with no row of its own takes the price in its heading: "Spell
    Scroll (Cantrip, 30 GP; Level 1, 50 GP)" prices two rows.
    """
    rows = {plain(row[0]).strip(): row for row in table_section.blocks[0].rows}
    records = []
    for section in parent.subsections:
        priced = PRICED.match(section.heading)
        if section is table_section or not priced:
            continue
        name = priced.group(1).strip()
        row = rows.get(name)
        records.append({"name": name, "kind": ItemKind.GEAR, "category": "Adventuring Gear",
                        "weight_lb": weight_lb(plain(row[1])) if row else None,
                        **price(plain(row[2]) if row else priced.group(2)),
                        "description": section_text(section), "section_id": section.id,
                        "source": source(section, pdf)})
    return records


def poisons(parent: Section, pdf: str) -> list[dict]:
    """Each Sample Poison: price from its heading, type from the italic line under it."""
    records = []
    for section in parent.subsections:
        priced = PRICED.match(section.heading)
        first = section.blocks[0] if section.blocks else None
        kind = (re.match(r"(\w+)\s+Poison", plain(first.runs))
                if isinstance(first, Paragraph) and all(r.italic for r in first.runs) else None)
        records.append({"name": (priced.group(1) if priced else section.heading).strip(), "kind": ItemKind.POISON,
                        "category": "Poison", "poison_type": kind.group(1) if kind else None,
                        **price(priced.group(2) if priced else ""), "weight_lb": None,
                        "description": section_text(section), "section_id": section.id,
                        "source": source(section, pdf)})
    return records


def rows_by_category(table: Table) -> list[tuple[list, str]]:
    """The table's item rows, each with the text of the category row it is under."""
    return [(row, plain(table.rows[category][0]).strip()) for row, category in zip(table.rows, table.under)
            if category is not None]


def table_section(sections: list[Section], caption: str) -> Section:
    """The section holding the table captioned ``caption``."""
    return next(s for s in walk(sections) if is_table(s, caption))


def is_table(section: Section, caption: str) -> bool:
    """Whether the section is the float of the table captioned ``caption``."""
    return (len(section.blocks) == 1 and isinstance(section.blocks[0], Table)
            and plain(section.blocks[0].caption) == caption)


def price(text: str) -> dict:
    """``cost`` as printed and ``cost_gp`` in gold pieces ("4 CP" is 0.04); None where not a price."""
    text = text.strip()
    found = COST.search(text)
    if not found:
        return {"cost": text or None, "cost_gp": None}
    return {"cost": text, "cost_gp": round(float(found.group(1).replace(",", ""))
                                           * Coin(found.group(2).upper()).in_gold, 4)}


def weight_lb(text: str) -> float | None:
    """A weight cell in pounds ("1½ lb." is 1.5); None for "\u2014" or "Varies"."""
    found = WEIGHT.search(text)
    if not found:
        return None
    whole = float(found.group(1).replace(",", "")) if found.group(1) else 0.0
    return whole + FRACTIONS.get(found.group(2) or "", 0.0)
