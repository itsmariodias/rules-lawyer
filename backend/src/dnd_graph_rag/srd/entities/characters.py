"""Classes, species, backgrounds and feats as records.

A class prints a Core Traits table, a "<Class> Features" table of its levels,
feature headings "Level 9: Brutal Strike" under "<Class> Class Features", and
one "<Class> Subclass: Name". Species, backgrounds and feats print bold labelled
fields and traits named in bold italics.
"""

from __future__ import annotations

import re

from ..model import Section, Table, plain
from ..output.render import render_runs
from ..sections import walk
from .records import (
    description,
    labelled_fields,
    named_entries,
    paragraphs_of,
    source,
)

# A Core Traits table's labels and the record fields they fill; the keys are the
# ones graph/ reads ("Saving Throw Proficiencies" was misread as "Saving Throw").
CORE_TRAITS = {"Primary Ability": "primary_ability", "Hit Point Die": "hit_point_die",
               "Saving Throw Proficiencies": "saving_throw", "Skill Proficiencies": "skill_proficiencies",
               "Weapon Proficiencies": "weapon_proficiencies", "Tool Proficiencies": "tool_proficiencies",
               "Armor Training": "armor_training", "Starting Equipment": "starting_equipment"}
FEATURE = re.compile(r"^Level (\d+): (.+)$")
SUBCLASS = re.compile(r"^(.+?) Subclass: (.+)$")
# A feat's category opens the italic line under it ("Epic Boon Feat (Prerequisite: ...)").
FEAT_CATEGORY = re.compile(r"^([A-Za-z ]*?Feat)\b")


def classes(sections: list[Section], pdf: str) -> list[dict]:
    """Every class, with its core traits, its level progression, and its and its subclass's features.

    Args:
        sections: The book's sections.
        pdf: The PDF's file name, recorded in each record's ``source``.

    Returns:
        One record per section under "Classes".
    """
    chapter = next(s for s in sections if s.heading == "Classes")
    return [class_record(section, pdf) for section in chapter.subsections]


def class_record(section: Section, pdf: str) -> dict:
    """One class's record."""
    name = section.heading
    record: dict = {"name": name, "section_id": section.id}
    for row in table(section, f"Core {name} Traits").rows:
        label = plain(row[0]).strip()
        if label in CORE_TRAITS:
            record[CORE_TRAITS[label]] = " ".join(" ".join(plain(cell) for cell in row[1:]).split())
    record["progression"] = progression(table(section, f"{name} Features"))
    features: list[dict] = []
    subclasses: list[dict] = []
    for child in section.subsections:
        if subclass := SUBCLASS.match(child.heading):
            own = features_of(child, subclass.group(2))
            subclasses.append({"name": subclass.group(2), "section_id": child.id,
                               "description": description(child), "features": own})
            features += own
        elif child.heading == f"{name} Class Features":
            features += features_of(child, None)
    record["features"] = features
    record["subclasses"] = subclasses
    record["source"] = source(section, pdf)
    return record


def table(section: Section, caption: str) -> Table:
    """The table captioned ``caption`` in the section's subtree."""
    return next(s.blocks[0] for s in walk(section.subsections)
                if len(s.blocks) == 1 and isinstance(s.blocks[0], Table) and plain(s.blocks[0].caption) == caption)


def progression(features_table: Table) -> list[dict]:
    """A class's levels: proficiency bonus, features, and its other columns as ``resources``."""
    labels = column_labels(features_table)
    levels = []
    for row in features_table.rows:
        cells = dict(zip(labels, (" ".join(plain(cell).split()) for cell in row)))
        level: dict = {"level": int(cells.pop("Level")),
                       "proficiency_bonus": int(cells.pop("Proficiency Bonus").lstrip("+")),
                       "features": [f.strip() for f in cells.pop("Class Features").split(",")
                                    if f.strip() not in ("", "\u2014")]}
        if resources := {label: value for label, value in cells.items() if value}:
            level["resources"] = resources
        levels.append(level)
    return levels


def column_labels(features_table: Table) -> list[str]:
    """Each column's label, its header rows joined top to bottom ("Proficiency" / "Bonus").

    A column labelled only by a digit is a spell slot level under a label
    spanning several columns, printed once over the first ("Spell Slots per
    Spell Level" over 1 to 9): it takes the nearest label above and to its
    left ("Spell Slots per Spell Level 3").
    """
    rows = [[plain(cell).strip() for cell in row] for row in features_table.header]
    labels = []
    for column, bottom in enumerate(rows[-1]):
        if bottom.isdigit():
            spanning = max((c, row[c]) for row in rows[:-1] for c in range(column + 1) if c < len(row) and row[c])
            labels.append(f"{spanning[1].strip('\u2014')} {bottom}")
        else:
            labels.append(" ".join(row[column] for row in rows if column < len(row) and row[column]))
    return labels


def features_of(section: Section, subclass: str | None) -> list[dict]:
    """The "Level N: Name" features under a class's or subclass's section."""
    return [{"level": int(found.group(1)), "name": found.group(2), "subclass": subclass,
             "description": description(child), "section_id": child.id}
            for child in section.subsections if (found := FEATURE.match(child.heading))]


def origins(sections: list[Section], heading: str, kind: str, pdf: str) -> list[dict]:
    """The species or backgrounds under ``heading``, each with its labelled fields and traits."""
    parent = next(s for s in walk(sections) if s.heading == heading)
    return [entity(section, kind, pdf) for section in parent.subsections]


def feats(sections: list[Section], pdf: str) -> list[dict]:
    """Every feat, with the category its italic line names (else its group's) and its group."""
    parent = next(s for s in walk(sections) if s.heading == "Feat Descriptions")
    records = []
    for group in parent.subsections:
        if not group.heading.endswith("Feats"):
            continue
        for section in group.subsections:
            record = entity(section, "feat", pdf)
            first = paragraphs_of(section)[0] if paragraphs_of(section) else None
            category = FEAT_CATEGORY.match(plain(first.runs)) if first and first.runs[0].italic else None
            record["category"] = category.group(1) if category else group.heading.removesuffix("s")
            record["group"] = group.heading
            records.append(record)
    return records


def entity(section: Section, kind: str, pdf: str) -> dict:
    """A species', background's or feat's record: its text, labelled fields and named traits.

    Traits are read from the whole subtree: a table printed mid-entry is a
    section of its own, and the traits after it are still the entry's.
    """
    record: dict = {"name": section.heading, "kind": kind, "section_id": section.id,
                    "description": description(section), "source": source(section, pdf)}
    record |= labelled_fields(paragraphs_of(section))
    traits = [{"name": name, "description": render_runs(runs).strip().lstrip(".").strip()}
              for part in walk([section]) for name, runs in named_entries(paragraphs_of(part))]
    if traits:
        record["traits"] = traits
    return record
