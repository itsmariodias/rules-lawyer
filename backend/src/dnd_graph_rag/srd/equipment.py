"""
Turn the SRD's equipment tables into flat item records.

Weapons and armour are printed as tables, not as sections, so without this
they exist only as rows of markdown inside a section's prose — a graph would
have to re-parse them out of text.  Adventuring gear is the other way round:
each item has its own section carrying the rules text, while its weight and
price live in a table elsewhere, so the two halves are joined here.

Each record is flat::

    {
      "name": "Longsword",
      "kind": "weapon",
      "category": "Martial Melee",
      "damage": {"dice": "1d8", "type": "Slashing"},
      "properties": ["Versatile (1d10)"],
      "mastery": "Sap",
      "weight_lb": 3.0,
      "cost": "15 GP", "cost_gp": 15.0,
      "source": {"pdf": ..., "page_start": 91, "page_end": 91}
    }

Prices are also normalised to gold pieces so that items can be compared and
ordered without every consumer reimplementing the coin table.
"""

from __future__ import annotations

import re

# Coin values in gold pieces, from the Coin Values table.
COIN_VALUE_GP: dict[str, float] = {
    "CP": 0.01, "SP": 0.1, "EP": 0.5, "GP": 1.0, "PP": 10.0,
}

# Vulgar fractions the book uses in weights ("1½ lb.").
_FRACTIONS = {"¼": 0.25, "½": 0.5, "¾": 0.75}

_COST_RE = re.compile(r"([\d,]+)\s*(CP|SP|EP|GP|PP)\b", re.IGNORECASE)
_WEIGHT_RE = re.compile(r"([\d,]*)\s*([¼½¾])?\s*lb", re.IGNORECASE)
# Almost every weapon rolls dice, but the Blowgun deals a flat 1 Piercing.
_DAMAGE_RE = re.compile(r"^(\d+d\d+|\d+)\s+(\w+)$")

# "Versatile (1d10)" and "Ammunition (Range 80/320; Bolt)" both contain commas
# inside their parentheses, so properties cannot be split on commas naively.
_PROPERTY_RE = re.compile(r"[^,(]+(?:\([^)]*\))?")


def parse_cost(text: str) -> tuple[str | None, float | None]:
    """``"4 CP"`` → ``("4 CP", 0.04)``.  Returns (printed, gold) or (None, None)."""
    text = (text or "").strip()
    m = _COST_RE.search(text)
    if not m:
        return (text or None), None
    amount = float(m.group(1).replace(",", ""))
    return text, round(amount * COIN_VALUE_GP[m.group(2).upper()], 4)


def parse_weight(text: str) -> float | None:
    """``"1½ lb."`` → ``1.5``.  Returns None for "—" and "Varies"."""
    m = _WEIGHT_RE.search(text or "")
    if not m:
        return None
    whole = float(m.group(1).replace(",", "")) if m.group(1) else 0.0
    return whole + _FRACTIONS.get(m.group(2) or "", 0.0)


def parse_damage(text: str) -> dict[str, str] | None:
    """``"1d8 Slashing"`` → ``{"dice": "1d8", "type": "Slashing"}``."""
    m = _DAMAGE_RE.match((text or "").strip())
    return {"dice": m.group(1), "type": m.group(2)} if m else None


def split_properties(text: str) -> list[str]:
    """Split a Properties cell, keeping parenthesised ranges intact."""
    text = (text or "").strip()
    if not text or text == "—":
        return []
    return [p.strip() for p in _PROPERTY_RE.findall(text) if p.strip()]


# ---------------------------------------------------------------------------
# Table access
# ---------------------------------------------------------------------------

def _strip_markup(text: str) -> str:
    return re.sub(r"[*_]+", "", text).strip()


def read_tables(content: str, keep_markup: bool = False) -> list[list[list[str]]]:
    """
    Read every markdown table in *content* as rows of cells.

    Set *keep_markup* to keep the bold and italic markers, which is how a
    label can still be told from its value when the two share a cell.
    """
    tables: list[list[list[str]]] = []
    rows: list[list[str]] = []
    for line in content.split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            if rows:
                tables.append(rows)
                rows = []
            continue
        if set(line) <= set("|- "):
            continue
        cells = line.strip("|").split("|")
        rows.append([c.strip() if keep_markup else _strip_markup(c) for c in cells])
    if rows:
        tables.append(rows)
    return tables


def find_table(nodes, header: tuple[str, ...]) -> tuple[list[list[str]], dict] | None:
    """
    Collect every table whose header row starts with *header*, as one table.

    Within a section, a table is located by its own header rather than by
    position, because the book sometimes prints one a subsection away from
    the prose that introduces it.  A long table is continued on the following
    page under a repeat of its header — the Adventuring Gear table runs to 81
    items that way — so the pieces are concatenated, keeping one header.
    Callers scope *nodes* to a section: "Item | Weight | Cost" is generic
    enough that Mounts and Vehicles would otherwise be swept in too.
    """
    merged: list[list[str]] = []
    source: dict | None = None
    for node in nodes:
        for rows in read_tables(node["content"]):
            if tuple(c.lower() for c in rows[0][: len(header)]) != header:
                continue
            if source is None:
                source = node
                merged.extend(rows)
            else:
                merged.extend(rows[1:])
    return (merged, source) if source else None


def subtree(nodes, heading: str) -> list[dict]:
    """The node with *heading* and everything under it, flattened."""
    def flatten(node):
        yield node
        for child in node["subsections"]:
            yield from flatten(child)

    for node in nodes:
        if node["heading"] == heading:
            return list(flatten(node))
    return []


def _is_group_row(row: list[str]) -> bool:
    """A category row names a group and leaves the rest of the columns blank."""
    return bool(row[0]) and not any(c.strip() for c in row[1:])


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------

def _source(node: dict) -> dict:
    src = node["source"]
    return {"pdf": src["pdf"], "page_start": src["page_start"], "page_end": src["page_end"]}


def extract_weapons(nodes) -> list[dict]:
    """Read the Weapons table, carrying each category row down onto its rows."""
    found = find_table(subtree(nodes, "Weapons"), ("name", "damage", "properties"))
    if not found:
        return []
    rows, node = found
    out: list[dict] = []
    category: str | None = None

    for row in rows[1:]:
        if _is_group_row(row):
            # "Simple Melee Weapons" → "Simple Melee"
            category = re.sub(r"\s*Weapons$", "", row[0]).strip()
            continue
        if len(row) < 6 or not row[0]:
            continue
        cost, cost_gp = parse_cost(row[5])
        out.append({
            "name": row[0],
            "kind": "weapon",
            "category": category,
            "damage": parse_damage(row[1]),
            "properties": split_properties(row[2]),
            "mastery": row[3] or None,
            "weight_lb": parse_weight(row[4]),
            "cost": cost,
            "cost_gp": cost_gp,
            "source": _source(node),
        })
    return out


def extract_armor(nodes) -> list[dict]:
    """Read the Armor table, including the Shield row."""
    found = find_table(subtree(nodes, "Armor"), ("armor", "armor class (ac)"))
    if not found:
        return []
    rows, node = found
    out: list[dict] = []
    category: str | None = None

    for row in rows[1:]:
        if _is_group_row(row):
            # "Light Armor (1 Minute to Don or Doff)" → "Light"
            category = re.split(r"\s+Armor\b|\s*\(", row[0])[0].strip()
            continue
        if len(row) < 6 or not row[0]:
            continue
        cost, cost_gp = parse_cost(row[5])
        strength = re.search(r"\d+", row[2])
        out.append({
            "name": row[0],
            "kind": "armor",
            "category": category,
            "armor_class": row[1] or None,
            "strength_requirement": int(strength.group()) if strength else None,
            "stealth_disadvantage": "disadvantage" in row[3].lower(),
            "weight_lb": parse_weight(row[4]),
            "cost": cost,
            "cost_gp": cost_gp,
            "source": _source(node),
        })
    return out


_GEAR_HEADING_RE = re.compile(r"^(.*?)\s*\(([^)]*)\)\s*$")


def extract_gear(nodes, gear_sections: list[dict]) -> list[dict]:
    """
    Join each Adventuring Gear section with its row in the gear table.

    The section carries the rules text and prints the price in its heading
    ("Acid (25 GP)"); the table carries weight and price for every item.
    """
    found = find_table(subtree(nodes, "Adventuring Gear"), ("item", "weight", "cost"))
    table: dict[str, list[str]] = {}
    node = None
    if found:
        rows, node = found
        table = {row[0]: row for row in rows[1:] if row and row[0]}

    out: list[dict] = []
    for section in gear_sections:
        m = _GEAR_HEADING_RE.match(section["heading"])
        name = (m.group(1) if m else section["heading"]).strip()
        printed = m.group(2).strip() if m else ""

        row = table.get(name)
        cost, cost_gp = parse_cost(row[2] if row else printed)
        out.append({
            "name": name,
            "kind": "gear",
            "category": "Adventuring Gear",
            "weight_lb": parse_weight(row[1]) if row else None,
            "cost": cost,
            "cost_gp": cost_gp,
            "description": section["content"],
            "section_id": section["id"],
            "source": _source(section),
        })
    return out


def extract_equipment(nodes, gear_sections: list[dict]) -> list[dict]:
    """Every weapon, suit of armour and piece of adventuring gear, in one list."""
    return (extract_weapons(nodes)
            + extract_armor(nodes)
            + extract_gear(nodes, gear_sections))
