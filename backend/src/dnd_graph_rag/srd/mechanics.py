"""
Attacks, saving throws, damage and imposed conditions, from entry text.

Stat block entries use fixed labels::

    _Melee Attack Roll:_ +9, reach 10 ft. _Hit:_ 12 (2d6 + 5) Bludgeoning damage.
    _Constitution Saving Throw:_ DC 16, each creature in a 60-foot Cone.
        _Failure:_ 22 (4d10) Poison damage. _Success:_ Half damage.

Spells say the same in prose, so ``parse_spell_mechanics`` reads less.
"""

from __future__ import annotations

import re

_SIGN = r"[+\-−]"


def _to_int(text: str) -> int:
    return int(text.replace("−", "-").replace("+", "").strip())


def _clean(text: str) -> str:
    return " ".join((text or "").split()).strip(" .,;")


# ---------------------------------------------------------------------------
# Uses: "(Recharge 5–6)", "(2/Day)"
# ---------------------------------------------------------------------------

_USES_RE = re.compile(r"\((Recharge[^)]*|\d+/Day[^)]*)\)", re.IGNORECASE)


def parse_uses(name: str) -> dict | None:
    """
    Read a usage limit such as ``(Recharge 5–6)`` or ``(2/Day)``.

    Args:
        name: An entry name as printed.

    Returns:
        ``{"type": "recharge" | "per_day" | "other", "printed", ...}`` with
        ``recharge_on`` or ``times`` as applicable; None without a limit.
    """
    m = _USES_RE.search(name or "")
    if not m:
        return None
    text = m.group(1).strip()
    recharge = re.search(r"Recharge\s*(\d+)(?:[–\-](\d+))?", text, re.IGNORECASE)
    if recharge:
        low = int(recharge.group(1))
        high = int(recharge.group(2)) if recharge.group(2) else low
        return {"type": "recharge", "printed": text, "recharge_on": [low, high]}
    per_day = re.search(r"(\d+)\s*/\s*Day", text, re.IGNORECASE)
    if per_day:
        return {"type": "per_day", "printed": text, "times": int(per_day.group(1))}
    return {"type": "other", "printed": text}


def strip_uses(name: str) -> str:
    """An entry name with its usage limit removed."""
    return _clean(_USES_RE.sub("", name or "")) or (name or "").strip()


# ---------------------------------------------------------------------------
# Damage
# ---------------------------------------------------------------------------

# Stat blocks print the average and the dice: "12 (2d6 + 5) Bludgeoning damage".
_STATBLOCK_DAMAGE_RE = re.compile(
    rf"(\d+)\s*\((\d+d\d+(?:\s*{_SIGN}\s*\d+)?)\)\s+([A-Z]\w+)\s+damage"
)
# Spells print only the dice: "8d6 Fire damage".
_SPELL_DAMAGE_RE = re.compile(r"(\d+d\d+(?:\s*[+\-]\s*\d+)?)\s+([A-Z]\w+)\s+damage")


def parse_damage(text: str, with_average: bool = True) -> list[dict]:
    """
    Every damage instance in a piece of text, in order.

    Args:
        text: Entry or spell text.
        with_average: Try the stat block form ``12 (2d6 + 5) Fire damage``
            first.  The dice-only form is used when it finds nothing.

    Returns:
        ``{"average", "dice", "type"}`` per instance; ``average`` is None for
        the dice-only form.
    """
    out: list[dict] = []
    if with_average:
        for m in _STATBLOCK_DAMAGE_RE.finditer(text or ""):
            out.append({
                "average": int(m.group(1)),
                "dice": _clean(m.group(2)).replace("−", "-"),
                "type": m.group(3),
            })
    if not out:
        for m in _SPELL_DAMAGE_RE.finditer(text or ""):
            out.append({"average": None, "dice": _clean(m.group(1)), "type": m.group(2)})
    return out


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------

# "has the X condition" (stat blocks) or "have the X condition" (spells).
# X may be an *and* list ("the Blinded, Deafened, and Poisoned conditions");
# 19 entries use one, including the Tarrasque's Thunderous Bellow.  *Or*
# lists are not read: "has the Grappled, Incapacitated, or Restrained
# condition" is usually target eligibility, and this regex cannot tell that
# from a choice of outcomes.
_CONDITION_NAME = r"[A-Z]\w+"
_CONDITION_RE = re.compile(
    rf"\bha(?:s|ve) the ({_CONDITION_NAME}(?:,\s+{_CONDITION_NAME})*"
    rf"(?:,?\s+and\s+{_CONDITION_NAME})?) conditions?\b"
)
_CONDITION_SPLIT_RE = re.compile(r",\s+and\s+|,\s+|\s+and\s+")

# Page markers can fall inside a condition list: the Remorhaz's swallowed
# creature "has the Blinded <!-- PAGE:320 --> and Restrained conditions".
_PAGE_MARKER_RE = re.compile(r"<!--\s*PAGE:\d+\s*-->")

# Words that turn "has the X condition" from something inflicted into a
# prerequisite, a duration, or a state being described or removed.
_NEGATION_RE = re.compile(
    r"\b(if|unless|while|whether|that|already|immune|no longer|"
    r"isn’t|isn't|aren’t|aren't|doesn’t|doesn't|don’t|don't|not)\b",
    re.IGNORECASE,
)
_CLAUSE_BOUNDARY_RE = re.compile(r"[.;,]")


def conditions_imposed(text: str) -> list[str]:
    """
    The conditions a piece of text inflicts, as opposed to mentions.

    A match is skipped when ``_NEGATION_RE`` hits in its own clause, i.e.
    after the last ``.``, ``;`` or ``,`` before it:

    * "While Charmed, the target has the Incapacitated condition": inflicts
    * "while the vampire has the Incapacitated condition": does not
    * "one creature within 5 feet that has the Prone condition": does not

    Args:
        text: Entry or spell text, possibly containing page markers.

    Returns:
        Condition names in order of first appearance, without duplicates.
    """
    text = _PAGE_MARKER_RE.sub(" ", text or "")
    found: list[str] = []
    for m in _CONDITION_RE.finditer(text):
        clause = _CLAUSE_BOUNDARY_RE.split(text[: m.start()])[-1]
        if _NEGATION_RE.search(clause):
            continue
        for name in _CONDITION_SPLIT_RE.split(m.group(1)):
            if name and name not in found:
                found.append(name)
    return found


# ---------------------------------------------------------------------------
# Stat block entries
# ---------------------------------------------------------------------------

_ATTACK_RE = re.compile(
    r"_(Melee|Ranged|Melee or Ranged) Attack Roll:_\s*"
    rf"({_SIGN}\d+)\s*(\([^)]*\))?"
)
_SAVE_RE = re.compile(r"_(\w+) Saving Throw:_\s*DC\s*(\d+)")
_REACH_RE = re.compile(r"reach\s+(\d+)\s*ft", re.IGNORECASE)
_RANGE_RE = re.compile(r"range\s+(\d+)(?:/(\d+))?\s*ft", re.IGNORECASE)

# The labelled segments an entry is divided into.
_SEGMENT_RE = re.compile(
    r"_((?:First |Second |Subsequent )?Failure(?: or Success)?"
    r"(?: by \d+ or More)?|Success|Hit(?: or Miss)?|Miss|Trigger|Response)"
    r"[^:_]*:_\s*"
)

ATTACK_KINDS = {"Melee": "melee", "Ranged": "ranged", "Melee or Ranged": "melee_or_ranged"}


def _segments(text: str) -> dict[str, str]:
    """Split an entry on its outcome labels, keeping the text before the first."""
    matches = list(_SEGMENT_RE.finditer(text))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        key = m.group(1).strip().lower().replace(" ", "_")
        out.setdefault(key, _clean(text[m.end():end]))
    return out


def parse_entry_mechanics(name: str, description: str) -> dict:
    """
    Read one stat block entry into structured mechanics.

    Args:
        name: The entry name, which carries any usage limit.
        description: The entry text.

    Returns:
        Whichever of ``uses``, ``attack``, ``save``, ``outcomes``,
        ``damage`` and ``conditions_imposed`` the entry states.
    """
    text = description or ""
    result: dict = {}

    uses = parse_uses(name)
    if uses:
        result["uses"] = uses

    attack = _ATTACK_RE.search(text)
    if attack:
        entry: dict = {
            "kind": ATTACK_KINDS[attack.group(1)],
            "bonus": _to_int(attack.group(2)),
        }
        if attack.group(3):
            entry["note"] = _clean(attack.group(3).strip("()"))
        reach = _REACH_RE.search(text)
        if reach:
            entry["reach_ft"] = int(reach.group(1))
        rng = _RANGE_RE.search(text)
        if rng:
            entry["range_ft"] = {"normal": int(rng.group(1)),
                                 "long": int(rng.group(2)) if rng.group(2) else None}
        result["attack"] = entry

    save = _SAVE_RE.search(text)
    if save:
        after = text[save.end():]
        result["save"] = {
            "ability": save.group(1),
            "dc": int(save.group(2)),
            "targets": _clean(_SEGMENT_RE.split(after)[0]).lstrip(", "),
        }

    segments = _segments(text)
    outcomes = {
        key: {"text": value, **({"damage": dmg} if (dmg := parse_damage(value)) else {})}
        for key, value in segments.items()
    }
    if outcomes:
        result["outcomes"] = outcomes

    damage = parse_damage(text)
    if damage:
        result["damage"] = damage
    conditions = conditions_imposed(text)
    if conditions:
        result["conditions_imposed"] = conditions
    return result


def annotate_creatures(creatures: list[dict]) -> int:
    """
    Merge ``parse_entry_mechanics`` into every entry of every creature.

    Args:
        creatures: Records from ``statblocks.extract_stat_blocks``; mutated.

    Returns:
        The number of entries that gained any mechanics.
    """
    parts = ("traits", "actions", "bonus_actions", "reactions", "legendary_actions")
    annotated = 0
    for creature in creatures:
        for part in parts:
            for entry in creature.get(part, []):
                mechanics = parse_entry_mechanics(entry.get("name") or "",
                                                  entry.get("description") or "")
                if mechanics:
                    entry.update(mechanics)
                    annotated += 1
    return annotated


# ---------------------------------------------------------------------------
# Spells
# ---------------------------------------------------------------------------

_SPELL_SAVE_RE = re.compile(
    r"\b(?:makes?|succeeds? on|succeed on|must succeed on)\s+an?\s+"
    r"(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)\s+saving throw",
    re.IGNORECASE,
)
_SPELL_ATTACK_RE = re.compile(r"\b(melee|ranged)\s+spell attack\b", re.IGNORECASE)


def parse_spell_mechanics(text: str) -> dict:
    """
    Read what a spell does from its prose.

    Args:
        text: The spell's description.

    Returns:
        Whichever of ``saving_throw``, ``attack``, ``damage`` and
        ``conditions_imposed`` the text states.
    """
    result: dict = {}

    save = _SPELL_SAVE_RE.search(text or "")
    if save:
        result["saving_throw"] = save.group(1).capitalize()

    attack = _SPELL_ATTACK_RE.search(text or "")
    if attack:
        result["attack"] = {"kind": attack.group(1).lower()}

    damage = parse_damage(text, with_average=False)
    if damage:
        result["damage"] = damage
    conditions = conditions_imposed(text)
    if conditions:
        result["conditions_imposed"] = conditions
    return result
