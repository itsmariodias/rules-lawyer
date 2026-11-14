"""Attacks, saving throws, outcomes, damage and imposed conditions, read from an entry's runs.

Stat block entries label their parts in italics ("Melee Attack Roll:", "Hit:",
"Constitution Saving Throw:", "Failure:"), so an entry splits at its italic
runs ending in a colon; damage and conditions are read from the plain text.
Spells say the same in prose, so ``spell_mechanics`` reads less.
"""

from __future__ import annotations

import math
import re

from ..model import Run, plain
from ..vocabulary import (
    Ability,
    AttackKind,
    DamageType,
    UsesType,
    alternatives,
)

SIGN = r"[+\-−]"
# "(Recharge 5–6)", "(2/Day)", "(3/Day, or 4/Day in Lair)".
USES = re.compile(r"\((Recharge[^)]*|\d+/Day[^)]*)\)", re.IGNORECASE)
# Stat blocks print the average and the dice: "12 (2d6 + 5) Bludgeoning damage".
STAT_BLOCK_DAMAGE = re.compile(rf"(\d+)\s*\((\d+d\d+(?:\s*{SIGN}\s*\d+)?)\)\s+({alternatives(DamageType)})\s+damage")
# Spells print only the dice: "8d6 Fire damage".
SPELL_DAMAGE = re.compile(rf"(\d+d\d+(?:\s*[+\-]\s*\d+)?)\s+({alternatives(DamageType)})\s+damage")
# "has the X condition" (stat blocks) or "have the X condition" (spells). X may be
# an *and* list ("the Blinded, Deafened, and Poisoned conditions"; 19 entries,
# among them the Tarrasque's Thunderous Bellow). *Or* lists are not read: "has the
# Grappled, Incapacitated, or Restrained condition" is usually target eligibility.
CONDITION = re.compile(r"\bha(?:s|ve) the ([A-Z]\w+(?:,\s+[A-Z]\w+)*(?:,?\s+and\s+[A-Z]\w+)?) conditions?\b")
CONDITION_LIST = re.compile(r",\s+and\s+|,\s+|\s+and\s+")
# Words that turn "has the X condition" from something inflicted into a
# prerequisite, a duration, or a state described or removed, in the clause
# before it (after the last "." "," or ";"): "While Charmed, the target has the
# Incapacitated condition" inflicts; "one creature that has the Prone condition"
# does not.
NEGATION = re.compile(r"\b(if|unless|while|whether|that|already|immune|no longer|isn’t|isn't|aren’t|aren't"
                      r"|doesn’t|doesn't|don’t|don't|not)\b", re.IGNORECASE)
CLAUSE_BOUNDARY = re.compile(r"[.;,]")
ATTACK_LABEL = re.compile(r"^(Melee or Ranged|Melee|Ranged) Attack Roll$")
SAVE_LABEL = re.compile(rf"^({alternatives(Ability)}) Saving Throw$")
OUTCOME_LABEL = re.compile(r"^((?:First |Second |Subsequent )?Failure(?: or Success)?(?: by \d+ or More)?"
                           r"|Success|Hit(?: or Miss)?|Miss|Trigger|Response)")
# An attack's bonus, and a note on it (9 attacks: "+5 (with Advantage if the target is
# Grappled by the ankheg)").
BONUS = re.compile(rf"^\s*({SIGN}\d+)\s*(\([^)]*\))?")
# A save's DC; a summoned creature's is prose ("DC equals your spell save DC"), so none.
DC = re.compile(r"\s*DC\s*(\d+)")
REACH = re.compile(r"reach\s+(\d+)\s*ft", re.IGNORECASE)
RANGE = re.compile(r"range\s+(\d+)(?:/(\d+))?\s*ft", re.IGNORECASE)
SPELL_SAVE = re.compile(r"\b(?:makes?|succeeds? on|succeed on|must succeed on)\s+an?\s+"
                        rf"({alternatives(Ability)})\s+saving throw", re.IGNORECASE)
SPELL_ATTACK = re.compile(r"\b(melee|ranged)\s+spell attack\b", re.IGNORECASE)


def to_int(text: str) -> int:
    """A printed signed number ("+9", "−1") as an int."""
    return int(text.replace("−", "-").replace("+", "").strip())


def clean(text: str) -> str:
    """Whitespace collapsed, and edge punctuation (" .,;") stripped."""
    return " ".join(text.split()).strip(" .,;")


def average(dice: str) -> int | None:
    """The floored average of a dice expression ("20d10 + 40"); None if it is not dice."""
    expression = dice.replace("−", "-").replace(" ", "")
    if not re.fullmatch(r"(\d+d\d+)([+-]\d+)*", expression):
        return None
    total = sum(int(n) * (int(sides) + 1) / 2 for n, sides in re.findall(r"(\d+)d(\d+)", expression))
    total += sum(int(constant) for constant in re.findall(r"[+-]\d+", re.sub(r"\d+d\d+", "", expression)))
    return math.floor(total)


def uses(name: str) -> dict | None:
    """An entry's usage limit, from its name: recharge, times per day, or other; None if unlimited."""
    found = USES.search(name)
    if not found:
        return None
    printed = found.group(1).strip()
    if recharge := re.search(r"Recharge\s*(\d+)(?:[–\-](\d+))?", printed, re.IGNORECASE):
        low = int(recharge.group(1))
        return {"type": UsesType.RECHARGE, "printed": printed,
                "recharge_on": [low, int(recharge.group(2)) if recharge.group(2) else low]}
    if per_day := re.search(r"(\d+)\s*/\s*Day", printed, re.IGNORECASE):
        return {"type": UsesType.PER_DAY, "printed": printed, "times": int(per_day.group(1))}
    return {"type": UsesType.OTHER, "printed": printed}


def damage(text: str, with_average: bool = True) -> list[dict]:
    """Every damage instance in the text, in order: ``{"average", "dice", "type"}``.

    The stat block form ("12 (2d6 + 5) Fire damage") is tried first; the
    dice-only form ("8d6 Fire damage", average None) only if it finds none.
    """
    found = [{"average": int(m.group(1)), "dice": clean(m.group(2)).replace("−", "-"), "type": m.group(3)}
             for m in STAT_BLOCK_DAMAGE.finditer(text)] if with_average else []
    return found or [{"average": None, "dice": clean(m.group(1)), "type": m.group(2)}
                     for m in SPELL_DAMAGE.finditer(text)]


def conditions_imposed(text: str) -> list[str]:
    """The conditions the text inflicts, as opposed to mentions, in order of first appearance."""
    found: list[str] = []
    for match in CONDITION.finditer(text):
        clause = CLAUSE_BOUNDARY.split(text[:match.start()])[-1]
        if NEGATION.search(clause):
            continue
        for name in CONDITION_LIST.split(match.group(1)):
            if name and name not in found:
                found.append(name)
    return found


def labelled_parts(runs: list[Run]) -> list[tuple[str | None, str]]:
    """The runs split at their labels (italic runs ending in a colon), each label with the
    plain text after it; the text before the first label has none."""
    runs = list(runs)
    for i in range(len(runs) - 1):
        # The book sets a label's colon roman twice (the Cultist Fanatic's "Hit",
        # the Magmin's "Failure").
        if runs[i].italic and not runs[i].text.strip().endswith(":") and runs[i + 1].text.startswith(":"):
            runs[i] = Run(runs[i].text.strip() + ":", runs[i].bold, True)
            runs[i + 1] = Run(runs[i + 1].text[1:], runs[i + 1].bold, runs[i + 1].italic)
    parts: list[tuple[str | None, str]] = [(None, "")]
    for run in runs:
        text = run.text.strip()
        if run.italic and not run.bold and text.endswith(":"):
            parts.append((text[:-1], ""))
        else:
            label, body = parts[-1]
            parts[-1] = (label, body + run.text)
    return parts


def entry_mechanics(name: str, runs: list[Run]) -> dict:
    """What a stat block entry does, from its name and the runs after it.

    Args:
        name: The entry's name as printed, which carries any usage limit.
        runs: The entry's text, its continuation paragraphs included.

    Returns:
        Whichever of ``uses``, ``attack``, ``save``, ``outcomes``, ``damage``
        and ``conditions_imposed`` the entry states.
    """
    text = plain(runs)
    result: dict = {}
    if limit := uses(name):
        result["uses"] = limit
    outcomes: dict[str, dict] = {}
    for label, body in labelled_parts(runs):
        if label is None:
            continue
        # A summoned creature's bonus is prose ("Bonus equals your spell attack
        # modifier", Animated Object): no number, so no attack is recorded.
        if (attack := ATTACK_LABEL.match(label)) and (bonus := BONUS.match(body)) and "attack" not in result:
            entry: dict = {"kind": AttackKind(attack.group(1).lower().replace(" ", "_")),
                           "bonus": to_int(bonus.group(1))}
            if bonus.group(2):
                entry["note"] = clean(bonus.group(2).strip("()"))
            if reach := REACH.search(text):
                entry["reach_ft"] = int(reach.group(1))
            if reach_range := RANGE.search(text):
                entry["range_ft"] = {"normal": int(reach_range.group(1)),
                                     "long": int(reach_range.group(2)) if reach_range.group(2) else None}
            result["attack"] = entry
        elif (save := SAVE_LABEL.match(label)) and (dc := DC.match(body)) and "save" not in result:
            result["save"] = {"ability": Ability(save.group(1)), "dc": int(dc.group(1)),
                              "targets": clean(body[dc.end():]).lstrip(", ")}
        elif outcome := OUTCOME_LABEL.match(label):
            outcome_text = clean(body)
            outcome_damage = damage(outcome_text)
            outcomes.setdefault(outcome.group(1).lower().replace(" ", "_"),
                                {"text": outcome_text, **({"damage": outcome_damage} if outcome_damage else {})})
    if outcomes:
        result["outcomes"] = outcomes
    if found := damage(text):
        result["damage"] = found
    if conditions := conditions_imposed(text):
        result["conditions_imposed"] = conditions
    return result


def spell_mechanics(text: str) -> dict:
    """What a spell does, from its prose: ``saving_throw``, ``attack``, ``damage`` and
    ``conditions_imposed``, whichever it states."""
    result: dict = {}
    if save := SPELL_SAVE.search(text):
        result["saving_throw"] = Ability(save.group(1).capitalize())
    if attack := SPELL_ATTACK.search(text):
        result["attack"] = {"kind": AttackKind(attack.group(1).lower())}
    if found := damage(text, with_average=False):
        result["damage"] = found
    if conditions := conditions_imposed(text):
        result["conditions_imposed"] = conditions
    return result
