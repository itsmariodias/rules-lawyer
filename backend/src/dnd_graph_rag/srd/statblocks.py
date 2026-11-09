"""
Stat blocks parsed as units, keyed off the 14.8pt card title.

Each record is flat and complete::

    {
      "name": "Ghast",
      "type": "Medium Undead", "alignment": "Chaotic Evil",
      "ac": 13,
      "initiative": {"bonus": 3, "score": 13, "advantage": false, "valid": true},
      "hp": {"average": 36, "formula": "8d8", "calculated": 36, "valid": true},
      "speed": {"walk": 30},
      "abilities": {"str": {"score": 16, "modifier": 3, "save": 3, ...}, ...},
      "senses": "...", "languages": "Common",
      "cr": "2", "xp": 450, "proficiency_bonus": 2,
      "traits":  [{"name": "Stench", "description": "..."}],
      "actions": [...], "bonus_actions": [...], "reactions": [...],
      "legendary_actions": [...],
      "source": {"pdf": ..., "page_start": 287, "page_end": 287},
      "warnings": []
    }
"""

from __future__ import annotations

import math
import re

from .layout import Line, reflow

# Unicode minus (U+2212) is used throughout the SRD for negative modifiers.
_UMINUS = "−"
_SIGN = r"[+\-−]"

# A passive score moves by 5 for Advantage or Disadvantage (Rules Glossary,
# "Initiative" and "Passive Perception").
ADVANTAGE_BONUS = 5

# Score, modifier, save.  The save's sign is optional because the book drops
# it in places (Young White Dragon prints "Int 6 −2 2").
_ABILITY_RE = re.compile(
    rf"\b(Str|Dex|Con|Int|Wis|Cha)\b\s*(\d+)\s*({_SIGN}\d+)\s*({_SIGN}?\d+)",
    re.IGNORECASE,
)

# Labels that appear as **Label** value on their own line in a stat block.
_LABELS = (
    "AC", "Initiative", "HP", "Speed", "Skills", "Gear", "Resistances",
    "Immunities", "Vulnerabilities", "Senses", "Languages", "CR",
)

_SECTION_FIELDS = {
    "traits": "traits",
    "actions": "actions",
    "bonus actions": "bonus_actions",
    "reactions": "reactions",
    "legendary actions": "legendary_actions",
}

# An entry inside a stat block section: "**_Multiattack._** The ghost makes …"
_ENTRY_RE = re.compile(r"\*\*_\s*(.+?)\s*_\*\*\s*")


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def _norm_minus(text: str) -> str:
    return text.replace(_UMINUS, "-")


def _to_int(text: str) -> int:
    return int(_norm_minus(text).replace("+", "").strip())


def ability_modifier(score: int) -> int:
    """
    Args:
        score: An ability score.

    Returns:
        ``floor((score - 10) / 2)``.
    """
    return (score - 10) // 2


def average_hp(formula: str) -> int | None:
    """
    Average of a hit point dice expression such as ``20d10 + 40``.

    Args:
        formula: The parenthesised part of an HP line.

    Returns:
        The floored average, or None when the formula is not dice (summoned
        creatures print prose that scales with the caster).
    """
    f = _norm_minus(formula).replace(" ", "")
    if not re.fullmatch(r"(\d+d\d+)([+-]\d+)*", f):
        return None
    total = 0.0
    for m in re.finditer(r"(\d+)d(\d+)", f):
        n, sides = int(m.group(1)), int(m.group(2))
        total += n * (sides + 1) / 2
    for m in re.finditer(r"[+-]\d+", re.sub(r"\d+d\d+", "", f)):
        total += int(m.group(0))
    return math.floor(total)


# ---------------------------------------------------------------------------
# Field parsers
# ---------------------------------------------------------------------------

def parse_speed(raw: str) -> dict[str, int]:
    """
    Args:
        raw: A Speed value, e.g. ``30 ft., Swim 40 ft.``.

    Returns:
        Feet per movement mode, e.g. ``{'walk': 30, 'swim': 40}``.
    """
    speeds: dict[str, int] = {}
    for m in re.finditer(r"(?:([A-Za-z]+)\s+)?(\d+)\s*ft", raw, re.IGNORECASE):
        speeds[(m.group(1) or "walk").lower()] = int(m.group(2))
    return speeds


def parse_bonus_list(raw: str) -> dict[str, int]:
    """
    Args:
        raw: A Skills value, e.g. ``Perception +10, Stealth +5``.

    Returns:
        Lowercased name to bonus, e.g. ``{'perception': 10, 'stealth': 5}``.
    """
    out: dict[str, int] = {}
    for m in re.finditer(rf"([A-Za-z][A-Za-z ]*?)\s*({_SIGN}\d+)", raw):
        key = m.group(1).strip().lower()
        if key:
            out[key] = _to_int(m.group(2))
    return out


def split_list(raw: str) -> list[str]:
    """Comma-separated values, stripped, empties dropped."""
    return [x.strip() for x in raw.split(",") if x.strip()]


# The SRD's fifteen conditions.
CONDITIONS = frozenset({
    "Blinded", "Charmed", "Deafened", "Exhaustion", "Frightened", "Grappled",
    "Incapacitated", "Invisible", "Paralyzed", "Petrified", "Poisoned",
    "Prone", "Restrained", "Stunned", "Unconscious",
})


def parse_defenses(raw: str) -> tuple[list[str], list[str]]:
    """
    Split an Immunities line into damage types and conditions.

    Each entry is sorted by its first word.  The book puts damage types
    before a semicolon and conditions after, but a line of conditions alone
    has none (Knight: ``Frightened``), which once filed 67 conditions as
    damage types.  A qualified entry keeps its note
    (``Charmed (with Mind Blank)``).

    Args:
        raw: e.g. ``Poison; Charmed, Exhaustion, Poisoned``.

    Returns:
        ``(damage_types, conditions)``.
    """
    damage: list[str] = []
    conditions: list[str] = []
    for entry in split_list(raw.replace(";", ",")):
        (conditions if entry.split()[0] in CONDITIONS else damage).append(entry)
    return damage, conditions


def parse_abilities(raw: str) -> dict[str, dict] | None:
    """
    Parse the six ability scores out of a flattened ability grid.

    Args:
        raw: e.g. ``**Str** 21 +5 +5 **Dex** …``.

    Returns:
        Per ability: score, modifier, save, ``modifier_valid`` and
        ``save_has_proficiency``.  None unless all six are found.
    """
    raw = re.sub(r"[*_]+", " ", _norm_minus(raw))
    abilities: dict[str, dict] = {}
    for m in _ABILITY_RE.finditer(raw):
        key = m.group(1).lower()
        if key in abilities:
            continue
        score = int(m.group(2))
        modifier, save = _to_int(m.group(3)), _to_int(m.group(4))
        abilities[key] = {
            "score": score,
            "modifier": modifier,
            "save": save,
            "modifier_valid": modifier == ability_modifier(score),
            "save_has_proficiency": save != modifier,
        }
    return abilities if len(abilities) == 6 else None


_CR_RE = re.compile(r"\*\*CR\*\*\s*([\d/]+|None)\s*(?:\(([^)]*)\))?", re.IGNORECASE)
# Usually "XP 2,300", occasionally "2,300 XP".
_XP_RE = re.compile(r"(?:XP\s*([\d,]+)|([\d,]+)\s*XP)", re.IGNORECASE)
_XP_LAIR_RE = re.compile(r"or\s+([\d,]+)\s+in\s+lair", re.IGNORECASE)
_PB_RE = re.compile(r"PB\s*\+?(\d+)", re.IGNORECASE)


def parse_challenge(raw: str) -> dict:
    """
    Args:
        raw: e.g. ``**CR** 21 (XP 33,000, or 41,000 in lair; PB +7)``.

    Returns:
        Whichever of ``cr``, ``xp``, ``xp_in_lair`` and
        ``proficiency_bonus`` are present; empty if no CR label matches.
    """
    m = _CR_RE.search(raw)
    if not m:
        return {}
    out: dict = {"cr": m.group(1)}
    detail = m.group(2) or ""
    xp = _XP_RE.search(detail)
    if xp:
        out["xp"] = int((xp.group(1) or xp.group(2)).replace(",", ""))
    lair = _XP_LAIR_RE.search(detail)
    if lair:
        out["xp_in_lair"] = int(lair.group(1).replace(",", ""))
    pb = _PB_RE.search(detail)
    if pb:
        out["proficiency_bonus"] = int(pb.group(1))
    return out


# ---------------------------------------------------------------------------
# Entry (trait / action) splitting
# ---------------------------------------------------------------------------

def parse_entries(text: str) -> list[dict]:
    """
    Split a stat block section into its named entries.

    Args:
        text: Reflowed section markup, entries opening ``**_Name._**``.

    Returns:
        ``{"name", "description"}`` per entry.  Text with no entry markers
        is one entry with ``name`` None.
    """
    matches = list(_ENTRY_RE.finditer(text))
    if not matches:
        body = text.strip()
        return [{"name": None, "description": body}] if body else []

    entries: list[dict] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        name = m.group(1).strip().rstrip(".:")
        description = text[m.end():end].strip().lstrip(".").strip()
        if name:
            entries.append({"name": name, "description": description})
    return entries


# ---------------------------------------------------------------------------
# Block segmentation
# ---------------------------------------------------------------------------

def _flatten(line: Line) -> str:
    """Render a line (or an ability table) as one whitespace-normalised string."""
    if line.rows:
        text = " ".join(" ".join(r.cells) for r in line.rows)
    else:
        text = line.markup
    return re.sub(r"\s+", " ", text.replace("\t", " ")).strip()


def iter_blocks(lines: list[Line]) -> list[tuple[int, Line, list[Line]]]:
    """
    Find every stat block in the document.

    A block runs from its title to the next heading.  "Traits", "Actions"
    and the like are not headings, so they stay inside.

    Args:
        lines: Output of ``layout.extract_lines``.

    Returns:
        ``(index, title, body)`` per block, where ``index`` is the title's
        position in ``lines`` (the key into ``lines_to_markdown``'s offsets).
    """
    blocks: list[tuple[int, Line, list[Line]]] = []
    for i, line in enumerate(lines):
        if not line.is_statblock_name:
            continue
        body: list[Line] = []
        seen_challenge = in_section = False
        for nxt in lines[i + 1:]:
            if nxt.is_heading:
                break
            # A block printed inside another entry (Giant Fly in Figurine of
            # Wondrous Power) is followed by that entry's prose with no
            # heading.  A named entry after CR with no section open ends it.
            if nxt.is_statblock_section:
                in_section = True
            elif seen_challenge and not in_section and nxt.markup.lstrip().startswith("**_"):
                break
            if "**CR**" in nxt.markup:
                seen_challenge = True
            body.append(nxt)
        blocks.append((i, line, body))
    return blocks


def _split_labels(text: str) -> list[tuple[str, str]]:
    """Split ``**AC** 13 **Initiative** +3 (13)`` into labelled fields."""
    pattern = re.compile(rf"\*\*({'|'.join(_LABELS)})\*\*", re.IGNORECASE)
    hits = list(pattern.finditer(text))
    out = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        out.append((m.group(1), text[m.end():end].strip()))
    return out


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def parse_stat_block(title: Line, body: list[Line], pdf_name: str,
                     char_start: int | None = None) -> dict:
    """
    Turn one stat block's lines into a flat creature record.

    Args:
        title: The 14.8pt title line.
        body: Lines from ``iter_blocks``.
        pdf_name: Recorded in ``source``.
        char_start: The title's offset in the markdown, if known.

    Returns:
        The record described in the module docstring.  Inconsistencies
        (HP, modifiers, Initiative, passive Perception) go to ``warnings``.
    """
    record: dict = {
        "name": title.text.strip(),
        "entity_type": "creature",
        "source": {
            "pdf": pdf_name,
            "page_start": title.page,
            "page_end": body[-1].page if body else title.page,
            "char_start": char_start,
        },
    }
    warnings: list[str] = []

    # --- header: everything before the first stat block section -------------
    header: list[Line] = []
    sections: dict[str, list[Line]] = {}
    current: str | None = None

    for line in body:
        if line.is_statblock_section:
            current = _SECTION_FIELDS.get(line.text.strip().lower().rstrip("."))
            if current:
                sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)
        else:
            header.append(line)

    # --- type / alignment ---------------------------------------------------
    for line in header:
        m = re.match(r"^_([^_]+)_$", _flatten(line))
        if m:
            parts = m.group(1).rsplit(",", 1)
            record["type"] = parts[0].strip()
            record["alignment"] = parts[1].strip() if len(parts) > 1 else None
            break

    # --- ability grid -------------------------------------------------------
    for line in header:
        if line.rows:
            abilities = parse_abilities(_flatten(line))
            if abilities:
                record["abilities"] = abilities
                bad = [k for k, v in abilities.items() if not v["modifier_valid"]]
                if bad:
                    warnings.append(f"ability modifier disagrees with score: {', '.join(bad)}")
            break

    if "abilities" not in record:
        abilities = parse_abilities(" ".join(_flatten(l) for l in header))
        if abilities:
            record["abilities"] = abilities

    # --- labelled fields ----------------------------------------------------
    fields: dict[str, str] = {}
    last: str | None = None
    for line in header:
        if line.rows:
            last = None
            continue
        text = _flatten(line)
        labelled = _split_labels(text)
        if not labelled:
            # A long field wraps onto an unlabelled line: Clay Golem's
            # Immunities lost four conditions to it.
            if last is not None:
                fields[last] = f"{fields[last]} {text}"
            continue
        last = None
        for label, value in labelled:
            if label not in fields:
                fields[label] = value
                last = label
            else:
                last = None

    if "AC" in fields:
        m = re.match(r"(\d+)", fields["AC"])
        if m:
            record["ac"] = int(m.group(1))

    if "Initiative" in fields:
        m = re.match(rf"({_SIGN}?\d+)\s*\((\d+)\)", _norm_minus(fields["Initiative"]))
        if m:
            # Validated in _resolve_initiative, which needs the traits.
            record["initiative"] = {"bonus": _to_int(m.group(1)),
                                    "score": int(m.group(2))}

    if "HP" in fields:
        m = re.match(r"(\d+)\s*\((.+?)\)", fields["HP"])
        if m:
            stated, formula = int(m.group(1)), m.group(2).strip()
            calculated = average_hp(formula)
            record["hp"] = {
                "average": stated,
                "formula": formula,
                "calculated": calculated,
                "valid": calculated is None or calculated == stated,
            }
            if calculated is not None and calculated != stated:
                warnings.append(
                    f"hit points {stated} do not match average of {formula} ({calculated})"
                )
        elif fields["HP"]:
            record["hp"] = {"average": None, "formula": fields["HP"],
                            "calculated": None, "valid": True}

    if "Speed" in fields:
        record["speed"] = parse_speed(fields["Speed"])
    if "Skills" in fields:
        record["skills"] = parse_bonus_list(fields["Skills"])
    if "Gear" in fields:
        record["gear"] = split_list(fields["Gear"])
    if "Resistances" in fields:
        record["resistances"] = split_list(fields["Resistances"])
    if "Vulnerabilities" in fields:
        record["vulnerabilities"] = split_list(fields["Vulnerabilities"])
    if "Immunities" in fields:
        damage, conditions = parse_defenses(fields["Immunities"])
        record["immunities"] = damage
        record["condition_immunities"] = conditions
    if "Senses" in fields:
        record["senses"] = fields["Senses"]
    if "Languages" in fields:
        record["languages"] = fields["Languages"]
    if "CR" in fields:
        record.update(parse_challenge(f"**CR** {fields['CR']}"))

    _check_passive_perception(record, warnings)

    # --- traits / actions ---------------------------------------------------
    for field_name, chunk_lines in sections.items():
        entries = parse_entries(reflow([_flatten(l) for l in chunk_lines]))
        if entries:
            record[field_name] = entries

    _resolve_initiative(record, warnings)

    record["warnings"] = warnings
    return record


# The only source of standing Advantage on Initiative in the SRD.
_INVISIBLE_TRAIT_RE = re.compile(r"\bhas the Invisible condition\b", re.IGNORECASE)


def has_initiative_advantage(record: dict) -> bool:
    """
    Whether a trait makes the creature permanently Invisible.

    Invisible grants Advantage on Initiative.  Only traits count: the
    Will-o'-Wisp turns Invisible as a Bonus Action, which does not apply when
    Initiative is rolled, and its printed score agrees.

    Args:
        record: A creature record with ``traits`` parsed.

    Returns:
        True if any trait states the creature has the Invisible condition.
    """
    return any(_INVISIBLE_TRAIT_RE.search(t.get("description") or "")
               for t in record.get("traits", []))


def _resolve_initiative(record: dict, warnings: list[str]) -> dict | None:
    """
    Check the Initiative score is 10 + bonus, +5 with Advantage.

    A mismatched score is replaced by the computed one and kept as
    ``printed_score``.  The Gray Ooze prints +5 with nothing granting
    Advantage (it lost False Appearance in the 2024 revision).

    Returns:
        The updated ``initiative`` entry, or None if the record has none.
    """
    entry = record.get("initiative")
    if not entry:
        return None

    bonus, printed = entry["bonus"], entry["score"]
    advantage = has_initiative_advantage(record)
    expected = 10 + bonus + (ADVANTAGE_BONUS if advantage else 0)

    entry["advantage"] = advantage
    entry["valid"] = printed == expected
    if not entry["valid"]:
        entry["score"] = expected
        entry["printed_score"] = printed
        if not advantage and printed == expected + ADVANTAGE_BONUS:
            warnings.append(
                f"printed Initiative score {printed} implies Advantage on Initiative, "
                f"but no trait grants it; using {expected} (10 {bonus:+d})"
            )
        else:
            warnings.append(
                f"printed Initiative score {printed} does not match "
                f"{expected} (10 {bonus:+d}"
                + (" +5 with Advantage)" if advantage else ")")
                + "; using the computed value"
            )
    return entry


def _check_passive_perception(record: dict, warnings: list[str]) -> None:
    """
    Warn when Passive Perception is not 10 + Wis (+PB or 2xPB) (±5).

    A mismatch usually means column bleed: the senses line and the ability
    grid came from different stat blocks.
    """
    senses = record.get("senses")
    abilities = record.get("abilities")
    if not senses or not abilities:
        return
    m = re.search(r"Passive Perception (\d+)", senses)
    if not m:
        return
    stated = int(m.group(1))
    wis = abilities["wis"]["modifier"]
    pb = record.get("proficiency_bonus", 0) or 0
    bases = {10 + wis, 10 + wis + pb, 10 + wis + 2 * pb}
    allowed = {base + swing for base in bases
               for swing in (0, ADVANTAGE_BONUS, -ADVANTAGE_BONUS)}
    if stated not in allowed:
        warnings.append(
            f"passive Perception {stated} is inconsistent with Wisdom {wis:+d} (PB {pb})"
        )


def extract_stat_blocks(lines: list[Line], pdf_name: str,
                        offsets: dict[int, int] | None = None) -> list[dict]:
    """
    Extract every stat block in the document, in page order.

    Args:
        lines: Output of ``layout.extract_lines``.
        pdf_name: Recorded in each record's ``source``.
        offsets: Line index to markdown offset, from ``lines_to_markdown``.
            Sets ``source.char_start``, which matches a creature to its
            section.

    Returns:
        One record per stat block.
    """
    offsets = offsets or {}
    return [parse_stat_block(title, body, pdf_name, offsets.get(i))
            for i, title, body in iter_blocks(lines)]
