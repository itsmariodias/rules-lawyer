"""
Extract D&D stat blocks from the SRD as self-contained records.

A stat block is a *card* in the book, not a section of the heading tree: its
title, defence line, ability grid, trait list and action list are one visual
unit that the surrounding H2/H3 headings only loosely describe.  Parsing it
as a unit — rather than assembling it from whatever prose happened to land
under a heading — is what makes the result safe to turn into graph nodes.

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

# Score, then modifier, then saving throw.  The saving throw's sign is
# optional: the book drops it on a handful of stat blocks (Young White
# Dragon prints "Int 6 −2 2"), and refusing those would lose all six
# abilities over one missing character.
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
    """Standard D&D modifier: floor((score - 10) / 2)."""
    return (score - 10) // 2


def average_hp(formula: str) -> int | None:
    """
    Expected hit points for a dice expression such as ``20d10 + 40``.

    Returns None when the formula is not a dice expression — some summoned
    creatures scale with the caster and print prose there instead.
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
    """``30 ft., Swim 40 ft.`` → ``{'walk': 30, 'swim': 40}``."""
    speeds: dict[str, int] = {}
    for m in re.finditer(r"(?:([A-Za-z]+)\s+)?(\d+)\s*ft", raw, re.IGNORECASE):
        speeds[(m.group(1) or "walk").lower()] = int(m.group(2))
    return speeds


def parse_bonus_list(raw: str) -> dict[str, int]:
    """``Perception +10, Stealth +5`` → ``{'perception': 10, 'stealth': 5}``."""
    out: dict[str, int] = {}
    for m in re.finditer(rf"([A-Za-z][A-Za-z ]*?)\s*({_SIGN}\d+)", raw):
        key = m.group(1).strip().lower()
        if key:
            out[key] = _to_int(m.group(2))
    return out


def split_list(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def parse_defenses(raw: str) -> tuple[list[str], list[str]]:
    """
    Split an Immunities line into damage types and conditions.

    The SRD writes ``Poison; Charmed, Exhaustion, Poisoned`` — damage types
    first, then a semicolon, then conditions.  Without the semicolon the
    whole line is damage types.
    """
    if ";" in raw:
        damage, conditions = raw.split(";", 1)
        return split_list(damage), split_list(conditions)
    return split_list(raw), []


def parse_abilities(raw: str) -> dict[str, dict] | None:
    """Parse the six ability scores out of a flattened ability grid."""
    # The grid arrives as "**Str** 21 +5 +5 **Dex** …"; emphasis markers sit
    # between the label and its score, so drop them before matching.
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
# The book writes "XP 2,300" almost everywhere but "2,300 XP" in a couple of
# places, so accept the number on either side of the label.
_XP_RE = re.compile(r"(?:XP\s*([\d,]+)|([\d,]+)\s*XP)", re.IGNORECASE)
_XP_LAIR_RE = re.compile(r"or\s+([\d,]+)\s+in\s+lair", re.IGNORECASE)
_PB_RE = re.compile(r"PB\s*\+?(\d+)", re.IGNORECASE)


def parse_challenge(raw: str) -> dict:
    """``**CR** 21 (XP 33,000, or 41,000 in lair; PB +7)`` → its parts."""
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
    """Split a stat block section into its named traits or actions."""
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
    Slice the document into (index, title line, body lines) triples, one per
    stat block.  The index is the title's position in *lines*, which ties the
    record back to its offset in the rendered markdown.

    A block runs from its title until the next heading of any level — stat
    block sections ("Traits", "Actions") are not headings, so they stay
    inside their block.
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
            # A stat block printed inside another entry (the Giant Fly inside
            # Figurine of Wondrous Power) is followed by that entry's prose
            # under no heading of its own.  Challenge Rating closes the
            # header, so a named entry appearing after it with no section
            # open belongs to the surrounding text, not to this creature.
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
    """Turn one stat block's lines into a flat creature record."""
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
    for line in header:
        if line.rows:
            continue
        for label, value in _split_labels(_flatten(line)):
            fields.setdefault(label, value)

    if "AC" in fields:
        m = re.match(r"(\d+)", fields["AC"])
        if m:
            record["ac"] = int(m.group(1))

    if "Initiative" in fields:
        m = re.match(rf"({_SIGN}?\d+)\s*\((\d+)\)", _norm_minus(fields["Initiative"]))
        if m:
            # Resolved once the traits are known — see _resolve_initiative.
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

    # --- cross-check passive Perception against Wisdom ----------------------
    _check_passive_perception(record, warnings)

    # --- traits / actions ---------------------------------------------------
    for field_name, chunk_lines in sections.items():
        entries = parse_entries(reflow([_flatten(l) for l in chunk_lines]))
        if entries:
            record[field_name] = entries

    _resolve_initiative(record, warnings)

    record["warnings"] = warnings
    return record


# A trait that simply states the creature has the Invisible condition, with no
# action or condition attached.  This is the only thing in the SRD that gives a
# monster standing Advantage on Initiative.
_INVISIBLE_TRAIT_RE = re.compile(r"\bhas the Invisible condition\b", re.IGNORECASE)


def has_initiative_advantage(record: dict) -> bool:
    """
    Whether anything in the stat block grants Advantage on Initiative rolls.

    The Invisible condition says "If you're Invisible when you roll Initiative,
    you have Advantage on the roll", so a creature that is simply always
    Invisible qualifies.  It has to be a *trait*: the Will-o'-Wisp turns
    Invisible with a Bonus Action, which is not true when Initiative is rolled,
    and its printed score reflects that.
    """
    return any(_INVISIBLE_TRAIT_RE.search(t.get("description") or "")
               for t in record.get("traits", []))


def _resolve_initiative(record: dict, warnings: list[str]) -> dict | None:
    """
    Reconcile a stat block's Initiative modifier with its Initiative score.

    Per the Rules Glossary, "Your Initiative score equals 10 plus your
    Dexterity modifier.  If you have Advantage on Initiative rolls, increase
    your Initiative score by 5.  If you have Disadvantage on those rolls,
    decrease that score by 5."  So a score sitting 5 above the modifier is how
    the book records a creature that rolls Initiative with Advantage.

    The +5 is only honoured when the stat block actually grants Advantage.
    The Gray Ooze prints a score 5 too high with nothing to justify it — it
    lost the False Appearance trait in the 2024 revision, and the score looks
    to have been left behind — so the rules-correct value is used and the
    printed one is kept alongside it under ``printed_score``.
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
    Cross-check Passive Perception against the ability grid.

    It is 10 + the creature's Wisdom (Perception) bonus — so plus proficiency
    where the creature is proficient, or twice it with Expertise — and ±5 for
    Advantage or Disadvantage, the same adjustment the Initiative score uses.
    A value outside that set means the senses line and the ability grid came
    from different stat blocks, which is what column bleed looks like.
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

    *offsets* maps a line's index to its character offset in the rendered
    markdown; passing it lets each record point at exactly where it was
    printed, which is how a creature is matched to its section.
    """
    offsets = offsets or {}
    return [parse_stat_block(title, body, pdf_name, offsets.get(i))
            for i, title, body in iter_blocks(lines)]
