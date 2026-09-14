"""
Structured records for the character-building half of the SRD: classes,
species, backgrounds and feats.

These are printed as sections rather than stat blocks, but their shape is
just as regular.  A class states its core traits in a two-column table, its
level progression in a wide one, and its features as headings that carry the
level in their text ("Level 9: Brutal Strike").  A species, background or
feat opens with a run of bold labels.  All of that survives as prose unless
it is read out deliberately, which is what this module does.

The level a feature is gained at is the useful part: it turns a class from a
page of text into a progression a graph can answer questions about.
"""

from __future__ import annotations

import re

from .equipment import find_table, read_tables, subtree

# "Level 9: Brutal Strike"
_FEATURE_HEADING_RE = re.compile(r"^Level\s+(\d+):\s*(.+)$")
# "Barbarian Subclass: Path of the Berserker"
_SUBCLASS_HEADING_RE = re.compile(r"^(.+?)\s+Subclass:\s*(.+)$")
# A run of bold labels: "**Creature Type:** Humanoid **Size:** Medium …"
_LABEL_RE = re.compile(r"\*\*([A-Z][A-Za-z ’']*?):?\*\*[:\s]*")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*_]+", "", text or "")).strip()


def _key(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")


def parse_labeled_fields(text: str) -> dict[str, str]:
    """
    Read a run of bold labels into a dict.

    Species, backgrounds and class core traits all open the same way — a
    sequence of "**Label:** value" on one line — so one reader serves them
    all.  A value runs until the next label or the end of the paragraph.
    """
    matches = list(_LABEL_RE.finditer(text or ""))
    fields: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = text[m.end():end].split("\n\n")[0]
        fields[_key(m.group(1))] = _clean(value)
    return fields


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

_TRAIT_LABEL_RE = re.compile(r"^\*\*([^*]+?)\*\*\s*(.*)$", re.DOTALL)


def _normalise_trait_rows(rows: list[list[str]]) -> list[tuple[str, str]]:
    """
    Repair the label/value pairs of a Core Traits table.

    Three things go wrong when these two-column tables are rebuilt from the
    page, and all three are visible in the cells themselves:

    * a label and the start of its value share the first cell, with the rest
      of the value in the second ("**Weapon Proficiencies** Simple weapons
      and Martial" | "weapons that have the Light property");
    * a value lands one row above its label, leaving each of them half empty
      (the Monk's Primary Ability);
    * "Proficiencies" is a bare sub-heading with no value at all.
    """
    pairs: list[tuple[str, str]] = []
    pending_value: str | None = None

    for row in rows:
        first = row[0] if row else ""
        rest = " ".join(row[1:]).strip() if len(row) > 1 else ""

        m = _TRAIT_LABEL_RE.match(first.strip())
        label = _clean(m.group(1)) if m else ""
        value = " ".join(part for part in (m.group(2) if m else first, rest) if part.strip())

        if not label:
            # A value with no label of its own: hold it for the next row.
            pending_value = _clean(value) or pending_value
            continue
        if not _clean(value) and pending_value:
            value, pending_value = pending_value, None

        if label and _clean(value):
            pairs.append((label, _clean(value)))
    return pairs


def _core_traits(nodes) -> dict[str, str]:
    """
    Read a class's "Core <Class> Traits" table, plus the labelled paragraphs
    printed beside it.

    Starting Equipment sits outside the table for several classes, as a bold
    label in the running text, so both sources are read and the table wins
    where they overlap.
    """
    traits: dict[str, str] = {}
    for node in nodes:
        for key, value in parse_labeled_fields(node["content"]).items():
            if key == "starting_equipment":
                traits.setdefault(key, value)

    for node in nodes:
        for rows in read_tables(node["content"], keep_markup=True):
            if not any("Primary Ability" in cell for row in rows for cell in row):
                continue
            for label, value in _normalise_trait_rows(rows):
                traits[_key(label)] = value
            return traits
    return traits


def _progression(nodes, class_name: str) -> list[dict]:
    """
    Read a "<Class> Features" table into one record per level.

    Its header wraps onto two printed lines ("Proficiency" above "Bonus"), so
    every row before the one starting "Level" is folded into the header.
    Columns beyond level, proficiency bonus and features differ per class —
    Rages, Sneak Attack, Spell Slots — and are kept as named resources.
    """
    found = find_table(subtree(nodes, f"{class_name} Class Features"), ("",))
    tables = [rows for node in subtree(nodes, class_name)
              for rows in read_tables(node["content"])
              if any(_clean(c) == "Level" for c in (rows[0] if rows else []))
              or (len(rows) > 1 and any(_clean(c) == "Level" for c in rows[1]))]
    if not tables:
        return []
    rows = tables[0]

    start = next(i for i, row in enumerate(rows)
                 if any(_clean(c) == "Level" for c in row))
    header = [
        " ".join(part for part in
                 (_clean(rows[j][i]) if i < len(rows[j]) else "" for j in range(start + 1))
                 if part).strip()
        for i in range(max(len(r) for r in rows[: start + 1]))
    ]

    out: list[dict] = []
    for row in rows[start + 1:]:
        if not row or not row[0].strip().isdigit():
            continue
        entry: dict = {"level": int(row[0].strip())}
        resources: dict[str, str] = {}
        for i, cell in enumerate(row[1:], start=1):
            name = header[i] if i < len(header) else f"column_{i}"
            value = _clean(cell)
            if name == "Proficiency Bonus":
                entry["proficiency_bonus"] = int(value.replace("+", "") or 0)
            elif name == "Class Features":
                entry["features"] = [f.strip() for f in value.split(",") if f.strip()]
            elif name and value:
                resources[name] = value
        if resources:
            entry["resources"] = resources
        out.append(entry)
    return out


def _features_of(node: dict, subclass: str | None) -> list[dict]:
    features = []
    for child in node["subsections"]:
        m = _FEATURE_HEADING_RE.match(child["heading"])
        if not m:
            continue
        features.append({
            "level": int(m.group(1)),
            "name": m.group(2).strip(),
            "subclass": subclass,
            "description": child["content"],
            "section_id": child["id"],
        })
    return features


def extract_classes(tree) -> list[dict]:
    """Every class, with its core traits, level progression and features."""
    classes_section = next((n for n in tree if n["heading"] == "Classes"), None)
    if not classes_section:
        return []

    out: list[dict] = []
    for node in classes_section["subsections"]:
        nodes = subtree([node], node["heading"])
        record: dict = {"name": node["heading"], "section_id": node["id"]}
        record.update(_core_traits(nodes))

        progression = _progression([node], node["heading"])
        if progression:
            record["progression"] = progression

        features: list[dict] = []
        subclasses: list[dict] = []
        for child in node["subsections"]:
            m = _SUBCLASS_HEADING_RE.match(child["heading"])
            if m:
                name = m.group(2).strip()
                sub_features = _features_of(child, name)
                subclasses.append({"name": name, "section_id": child["id"],
                                   "description": child["content"],
                                   "features": sub_features})
                features += sub_features
            elif child["heading"].endswith("Class Features"):
                features += _features_of(child, None)

        record["features"] = features
        if subclasses:
            record["subclasses"] = subclasses
        record["source"] = {k: node["source"][k]
                            for k in ("pdf", "page_start", "page_end")}
        out.append(record)
    return out


# ---------------------------------------------------------------------------
# Species, backgrounds and feats
# ---------------------------------------------------------------------------

def _entity_from_section(node: dict, kind: str) -> dict:
    record: dict = {
        "name": node["heading"],
        "kind": kind,
        "section_id": node["id"],
        "description": node["content"],
        "source": {k: node["source"][k] for k in ("pdf", "page_start", "page_end")},
    }
    record.update(parse_labeled_fields(node["content"]))

    # A table printed mid-entry splits the rest of the traits into a child
    # section (the Draconic Ancestors table does this to the Dragonborn), so
    # named entries are gathered from the whole subtree, not just the top.
    traits = [
        {"name": e["name"], "description": e["description"]}
        for n in _flatten(node) for e in n.get("entries", [])
    ]
    if traits:
        record["traits"] = traits
    return record


def _flatten(node: dict):
    yield node
    for child in node["subsections"]:
        yield from _flatten(child)


def _children_of(nodes, heading: str) -> list[dict]:
    for node in nodes:
        if node["heading"] == heading:
            return node["subsections"]
    return []


def extract_species(nodes) -> list[dict]:
    return [_entity_from_section(n, "species")
            for n in _children_of(nodes, "Species Descriptions")]


def extract_backgrounds(nodes) -> list[dict]:
    return [_entity_from_section(n, "background")
            for n in _children_of(nodes, "Background Descriptions")]


_FEAT_CATEGORY_RE = re.compile(r"^_([A-Za-z ]*?Feat)_", re.MULTILINE)


def extract_feats(nodes) -> list[dict]:
    """
    Every feat, with the category the book prints under its name.

    Feats are grouped into "Origin Feats", "General Feats" and so on; the
    category is also italicised under each feat, which is the more reliable
    of the two because a feat keeps it wherever it is reprinted.
    """
    out: list[dict] = []
    for group in _children_of(nodes, "Feat Descriptions"):
        if not group["heading"].endswith("Feats"):
            continue
        for node in group["subsections"]:
            record = _entity_from_section(node, "feat")
            m = _FEAT_CATEGORY_RE.search(node["content"])
            record["category"] = (m.group(1) if m else group["heading"].rstrip("s")).strip()
            record["group"] = group["heading"]
            out.append(record)
    return out


# ---------------------------------------------------------------------------
# Poisons
# ---------------------------------------------------------------------------

_POISON_HEADING_RE = re.compile(r"^(.*?)\s*\(([^)]*)\)\s*$")
_POISON_TYPE_RE = re.compile(r"^_(\w+)\s+Poison_", re.MULTILINE)


_POISON_TYPES_INTRO = "Poisons come in the following four types:"
_POISON_TYPE_LABEL_RE = re.compile(r"\*\*([A-Z][A-Za-z ]+?)\.\*\*\s*")


def extract_poison_types(nodes) -> list[dict]:
    """
    The four delivery types, from the paragraph that introduces them.

    A closed vocabulary printed the same way the damage types are: one
    passage defining all of them, so they are not 1:1 with a section and
    belong in the glossary beside the other typed terms rather than in the
    tree.  Each poison names one, which is what makes the pairing useful —
    a poison can be read together with what its type actually does.

    Returns nothing if the book stops introducing them this way, rather than
    guessing at the labels.
    """
    for node in nodes:
        if node["heading"] != "Poison":
            continue
        start = node["content"].find(_POISON_TYPES_INTRO)
        if start < 0:
            continue
        body = node["content"][start + len(_POISON_TYPES_INTRO):]
        labels = list(_POISON_TYPE_LABEL_RE.finditer(body))
        return [
            {
                "name": label.group(1),
                "term_type": "poison type",
                "description": body[label.end():
                                    labels[i + 1].start()
                                    if i + 1 < len(labels) else len(body)].strip(),
                "section_id": node["id"],
                "source": {k: node["source"][k]
                           for k in ("pdf", "page_start", "page_end")},
            }
            for i, label in enumerate(labels)
        ]
    return []


def extract_poisons(nodes) -> list[dict]:
    """
    The Sample Poisons, which are priced items like any other equipment.

    Their heading carries the price and their first line the delivery type
    ("Ingested", "Inhaled", "Contact", "Injury").
    """
    from .equipment import parse_cost

    out: list[dict] = []
    for node in _children_of(nodes, "Sample Poisons"):
        m = _POISON_HEADING_RE.match(node["heading"])
        name = (m.group(1) if m else node["heading"]).strip()
        cost, cost_gp = parse_cost(m.group(2) if m else "")
        kind = _POISON_TYPE_RE.search(node["content"])
        out.append({
            "name": name,
            "kind": "poison",
            "category": "Poison",
            "poison_type": kind.group(1) if kind else None,
            "cost": cost,
            "cost_gp": cost_gp,
            "weight_lb": None,
            "description": node["content"],
            "section_id": node["id"],
            "source": {k: node["source"][k]
                       for k in ("pdf", "page_start", "page_end")},
        })
    return out


# ---------------------------------------------------------------------------
# Damage types
# ---------------------------------------------------------------------------

def extract_damage_types(nodes) -> list[dict]:
    """
    The damage types, from the glossary's Damage Types table.

    They are a closed vocabulary that resistances, immunities and every
    attack refer to, so they belong in the graph as nodes rather than as
    repeated strings.  The book prints the table in two halves side by side.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for node in nodes:
        if node["heading"] != "Damage Types":
            continue
        for rows in read_tables(node["content"]):
            if not rows or _clean(rows[0][0]).lower() != "type":
                continue
            for row in rows[1:]:
                name = _clean(row[0])
                if name and name not in seen:
                    seen.add(name)
                    out.append({
                        "name": name,
                        "term_type": "damage type",
                        "description": _clean(row[1]) if len(row) > 1 else "",
                        "section_id": node["id"],
                        "source": {k: node["source"][k]
                                   for k in ("pdf", "page_start", "page_end")},
                    })
    return out
