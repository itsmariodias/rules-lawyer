"""Creature records from stat block sections: fields, scores and entries, read and checked."""

from __future__ import annotations

import re

from rules_lawyer.srd.entities.mechanics import SIGN, average, entry_mechanics, to_int
from rules_lawyer.srd.entities.records import named_entries
from rules_lawyer.srd.model import Paragraph, Run, Section, StatBlock, plain
from rules_lawyer.srd.output.render import render_runs
from rules_lawyer.srd.sections import walk
from rules_lawyer.srd.vocabulary import Condition, EntityType, StatPart

# A passive score moves by 5 with Advantage or Disadvantage (Rules Glossary,
# "Initiative" and "Passive Perception").
ADVANTAGE = 5
# The only standing Advantage on Initiative in the SRD: a trait making the creature
# Invisible (the Invisible Stalker's +7 (22)).
INVISIBLE = re.compile(r"\bhas the Invisible condition\b", re.IGNORECASE)


def creatures(sections: list[Section], pdf: str) -> list[dict]:
    """A record for every stat block, in reading order.

    Args:
        sections: The book's sections, offsets written.
        pdf: The PDF's file name, recorded in each record's ``source``.

    Returns:
        One record per stat block: its fields parsed, each entry with its
        mechanics, and ``warnings`` where the book disagrees with itself.
    """
    return [creature(section, pdf) for section in walk(sections) if section.entity_type == EntityType.CREATURE]


def creature(section: Section, pdf: str) -> dict:
    """The record for one stat block section."""
    block: StatBlock = section.blocks[0]
    kind, _, alignment = plain(block.subtitle).rpartition(",")
    record: dict = {"name": block.name, "entity_type": "creature",
                    "source": {"pdf": pdf, "page_start": section.source.page_start,
                               "page_end": section.source.page_end, "char_start": section.source.char_start},
                    "type": (kind or alignment).strip(), "alignment": alignment.strip() if kind else None,
                    "abilities": abilities(block.abilities)}
    warnings = [f"ability modifier disagrees with score: {name}"
                for name, ability in record["abilities"].items() if not ability["modifier_valid"]]
    fields: dict[str, list[Run]] = {}
    for field in block.fields:
        fields.setdefault(field.label, field.value)
    text = {label: plain(value) for label, value in fields.items()}
    if "AC" in text:
        record["ac"] = int(re.match(r"\d+", text["AC"]).group(0))
    if initiative := re.match(rf"({SIGN}?\d+)\s*\((\d+)\)", text.get("Initiative", "")):
        record["initiative"] = {"bonus": to_int(initiative.group(1)), "score": int(initiative.group(2))}
    if "HP" in text:
        record["hp"] = hit_points(text["HP"], warnings)
    if "Speed" in text:
        record["speed"] = {(mode or "walk").lower(): int(feet)
                           for mode, feet in re.findall(r"(?:([A-Za-z]+)\s+)?(\d+)\s*ft", text["Speed"])}
    if "Skills" in text:
        record["skills"] = {name.strip().lower(): to_int(bonus)
                            for name, bonus in re.findall(rf"([A-Za-z][A-Za-z ]*?)\s*({SIGN}\d+)", text["Skills"])}
    for label, key in (("Gear", "gear"), ("Resistances", "resistances"), ("Vulnerabilities", "vulnerabilities")):
        if label in fields:
            record[key] = listed(render_runs(fields[label]))
    if "Immunities" in fields:
        # Damage types come before conditions, but a line of conditions alone (the
        # Knight's "Frightened") has no semicolon: each entry is sorted by its name.
        entries = listed(render_runs(fields["Immunities"]).replace(";", ","))
        record["immunities"] = [entry for entry in entries if entry.split()[0] not in Condition]
        record["condition_immunities"] = [entry for entry in entries if entry.split()[0] in Condition]
    for label, key in (("Senses", "senses"), ("Languages", "languages")):
        if label in fields:
            record[key] = render_runs(fields[label])
    if "CR" in text:
        record |= challenge(text["CR"])
    passive_perception(record, warnings)
    for part in block.sections:
        if found := entries_of(part.entries):
            record[StatPart(part.title).field] = found
    resolve_initiative(record, warnings)
    record["warnings"] = warnings
    return record


def abilities(rows: list[list[str]]) -> dict[str, dict]:
    """Each ability's score, modifier and save, checked: a save other than the modifier is proficient."""
    found = {}
    for name, score, modifier, save in rows:
        score_value, modifier_value, save_value = int(score), to_int(modifier), to_int(save)
        found[name.lower()] = {"score": score_value, "modifier": modifier_value, "save": save_value,
                               "modifier_valid": modifier_value == (score_value - 10) // 2,
                               "save_has_proficiency": save_value != modifier_value}
    return found


def hit_points(value: str, warnings: list[str]) -> dict:
    """The HP field: stated average, formula, and the formula's own average where it is dice."""
    found = re.match(r"(\d+)\s*\((.+?)\)", value)
    if not found:
        return {"average": None, "formula": value, "calculated": None, "valid": True}
    stated, formula = int(found.group(1)), found.group(2).strip()
    calculated = average(formula)
    if calculated is not None and calculated != stated:
        warnings.append(f"hit points {stated} do not match average of {formula} ({calculated})")
    return {"average": stated, "formula": formula, "calculated": calculated,
            "valid": calculated is None or calculated == stated}


def listed(value: str) -> list[str]:
    """A comma-separated field's entries."""
    return [entry.strip() for entry in value.split(",") if entry.strip()]


def challenge(value: str) -> dict:
    """The CR field: "10 (XP 5,900, or 7,200 in lair; PB +4)"."""
    found = re.match(r"([\d/]+|None)\s*(?:\(([^)]*)\))?", value)
    record: dict = {"cr": found.group(1)}
    detail = found.group(2) or ""
    if xp := re.search(r"(?:XP\s*([\d,]+)|([\d,]+)\s*XP)", detail):
        record["xp"] = int((xp.group(1) or xp.group(2)).replace(",", ""))
    if lair := re.search(r"or\s+([\d,]+)\s+in\s+lair", detail, re.IGNORECASE):
        record["xp_in_lair"] = int(lair.group(1).replace(",", ""))
    if bonus := re.search(r"PB\s*\+?(\d+)", detail):
        record["proficiency_bonus"] = int(bonus.group(1))
    return record


def entries_of(paragraphs: list[Paragraph]) -> list[dict]:
    """A stat block section's entries with their mechanics. A paragraph not led by a name in
    bold italics continues the entry before it ("**At Will:** ..." after "**_Spellcasting._**",
    the Vampire's "**Sunlight.**" in "**_Vampire Weakness._**")."""
    return [{"name": name, "description": render_runs(runs).strip().lstrip(".").strip(),
             **entry_mechanics(name, runs)} for name, runs in named_entries(paragraphs)]


def passive_perception(record: dict, warnings: list[str]) -> None:
    """Warn if Passive Perception is not 10 + Wis (+ PB or 2 x PB), give or take 5."""
    stated = re.search(r"Passive Perception (\d+)", record.get("senses", ""))
    if not stated or "abilities" not in record:
        return
    wisdom = record["abilities"]["wis"]["modifier"]
    bonus = record.get("proficiency_bonus") or 0
    allowed = {10 + wisdom + proficient * bonus + swing for proficient in (0, 1, 2) for swing in (0, ADVANTAGE, -ADVANTAGE)}
    if int(stated.group(1)) not in allowed:
        warnings.append(f"passive Perception {stated.group(1)} is inconsistent with Wisdom {wisdom:+d} (PB {bonus})")


def resolve_initiative(record: dict, warnings: list[str]) -> None:
    """Check the Initiative score is 10 + bonus (+5 with Advantage); a wrong one is replaced.

    The printed score stays as ``printed_score``. The Gray Ooze prints +5 with
    nothing granting Advantage (it lost False Appearance in the 2024 revision).
    """
    initiative = record.get("initiative")
    if not initiative:
        return
    advantage = any(INVISIBLE.search(trait["description"]) for trait in record.get("traits", []))
    bonus, printed = initiative["bonus"], initiative["score"]
    expected = 10 + bonus + (ADVANTAGE if advantage else 0)
    initiative["advantage"], initiative["valid"] = advantage, printed == expected
    if printed == expected:
        return
    initiative["score"], initiative["printed_score"] = expected, printed
    if not advantage and printed == expected + ADVANTAGE:
        warnings.append(f"printed Initiative score {printed} implies Advantage on Initiative, "
                        f"but no trait grants it; using {expected} (10 {bonus:+d})")
    else:
        warnings.append(f"printed Initiative score {printed} does not match {expected} (10 {bonus:+d}"
                        + (" +5 with Advantage)" if advantage else ")") + "; using the computed value")


def check_mechanics(records: list[dict]) -> dict:
    """Damage averages against their dice, and attack bonuses against an ability modifier
    plus the proficiency bonus (an attack with a note is skipped: its bonus is not the sum).

    Returns:
        Counts checked, and the mismatches of each.
    """
    damage_checked, damage_bad, bonus_checked, bonus_bad = 0, [], 0, []
    for record in records:
        modifiers = {ability["modifier"] for ability in record["abilities"].values()}
        bonus = record.get("proficiency_bonus")
        for part in StatPart:
            for entry in record.get(part.field, []):
                for instance in entry.get("damage", []):
                    if instance["average"] is not None:
                        damage_checked += 1
                        if average(instance["dice"]) != instance["average"]:
                            damage_bad.append(f"{record['name']}/{entry['name']}: "
                                              f"{instance['average']} vs {instance['dice']}")
                attack = entry.get("attack")
                if attack and "note" not in attack and bonus:
                    bonus_checked += 1
                    if attack["bonus"] not in {modifier + bonus for modifier in modifiers}:
                        bonus_bad.append(f"{record['name']}/{entry['name']}: {attack['bonus']:+d}")
    return {"damage_averages_checked": damage_checked, "damage_average_mismatches": damage_bad,
            "attack_bonuses_checked": bonus_checked, "attack_bonus_mismatches": bonus_bad}
