"""
Stage 1 orchestration: section tree, entity typing, validation, and the CLI.

    srd-parse [--pdf PATH] [--out PATH] [--markdown PATH]

The artifact::

    {
      "meta":       { pdf, pages, generated, counts },
      "sections":   [ nested section tree ],
      "creatures":  [ flat stat block records ],
      "validation": { index reconciliation and every warning raised }
    }

``char_start``/``char_end`` on every section index the markdown written
beside the JSON.
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

from ..config import anchors_path_for, get_settings, markdown_path_for
from .character import (extract_backgrounds, extract_classes, extract_damage_types,
                        extract_feats, extract_poisons, extract_poison_types,
                        extract_species)
from .equipment import extract_equipment
from .layout import Line, extract_lines, lines_to_markdown
from .mechanics import annotate_creatures, parse_spell_mechanics
from .references import extract_glossary, extract_references, mark_glossary_nodes
from .statblocks import average_hp, extract_stat_blocks

_PAGE_MARKER_RE = re.compile(r"<!-- PAGE:(\d+) -->")
_EMPHASIS_RE = re.compile(r"\*{1,2}(.+?)\*{1,2}")


# ---------------------------------------------------------------------------
# Entity typing
# ---------------------------------------------------------------------------
# A section is "rule" unless independent evidence says otherwise: the subtitle
# the book prints (spell, magic_item), a stat block (creature,
# creature_group), membership of an entry set, a glossary tag, or being the
# section an extracted record names (``type_from_records``).  A chapter's
# position alone types nothing: "Classes" once made every heading, table and
# spell list under it a class_feature.

FRONT_MATTER = {"Legal Information", "Contents", "Index of Stat Blocks"}

# Chapters whose sections are grouped by the stat blocks they hold.  Outside
# them a stat block (a summoned creature, a figurine) leaves the spell or item
# printing it typed as that.
MONSTER_CHAPTERS = {"Monsters", "Monsters A–Z", "Animals"}

# Headings introducing a closed set of entries that are typed as entities
# rather than left as "rule".
ENTRY_SET_ENTITY_TYPES: dict[str, str] = {
    "Environmental Effects": "environmental_effect",
    "Example Traps": "trap",
    "Example Contagions": "contagion",
    # Options chosen through a feature (Metamagic, Eldritch Invocations).
    "Metamagic Options": "class_feature",
    "Eldritch Invocation Options": "class_feature",
}


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def strip_markup(text: str) -> str:
    """Text with ``*``/``**`` emphasis and underscores removed."""
    return _EMPHASIS_RE.sub(r"\1", text).replace("_", "").strip()


def clean_content(text: str) -> str:
    """Text with page markers removed and the blank lines they leave collapsed."""
    text = _PAGE_MARKER_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def build_page_index(markdown: str) -> list[tuple[int, int]]:
    """``(offset, page)`` for every page marker, in order."""
    return [(m.start(), int(m.group(1))) for m in _PAGE_MARKER_RE.finditer(markdown)]


def page_at(page_index: list[tuple[int, int]], pos: int) -> int:
    """
    Args:
        page_index: Output of ``build_page_index``.
        pos: A character offset in the markdown.

    Returns:
        The page the offset falls on; 1 before the first marker.
    """
    offsets = [p[0] for p in page_index]
    idx = bisect.bisect_right(offsets, pos) - 1
    return page_index[idx][1] if idx >= 0 else 1


def page_range(page_index: list[tuple[int, int]], start: int, end: int) -> tuple[int, int]:
    """
    The first and last page a character range touches.

    Not just the pages at its two ends: a float placed back in its section
    (``layout.place_floats``) can bring in a page from either side.

    Args:
        page_index: Output of ``build_page_index``.
        start: Start of the range.
        end: End of the range.

    Returns:
        ``(page_start, page_end)``.
    """
    pages = [page_at(page_index, start), page_at(page_index, end)]
    pages += [page for offset, page in page_index if start <= offset < end]
    return min(pages), max(pages)


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------

# Level 6 is stat block sections ("Traits", "Actions"), already split into
# entries on the creature records; they stay in their parent's content.
MAX_HEADING_LEVEL = 5


def first_heading_level(body: str, min_level: int) -> int | None:
    """The shallowest heading level at or below ``min_level`` present in ``body``."""
    for level in range(min_level, MAX_HEADING_LEVEL + 1):
        if re.search(rf'^{"#" * level} ', body, re.MULTILINE):
            return level
    return None


def split_on_level(body: str, level: int) -> list[tuple[str, str, int, int]]:
    """
    Split a body on headings of exactly ``level``.

    Returns:
        ``(heading, body, heading_start, body_start)`` per heading, offsets
        relative to ``body``.
    """
    pattern = re.compile(rf'^{"#" * level} (.+)$', re.MULTILINE)
    matches = list(pattern.finditer(body))
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out.append((m.group(1).strip(), body[m.end():end], m.start(), m.end()))
    return out


def direct_content(body: str, child_level: int | None) -> str:
    """The prose under a heading, before its first child heading."""
    if child_level is None:
        return body.strip()
    m = re.search(rf'^{"#" * child_level} ', body, re.MULTILINE)
    return (body[: m.start()] if m else body).strip()


def build_nodes(body: str, min_level: int, id_prefix: str, offset: int,
                page_index: list[tuple[int, int]], pdf_name: str) -> list[dict]:
    """
    Recursively build section nodes from markdown.

    Args:
        body: Markdown to split.
        min_level: Shallowest heading level to consider.
        id_prefix: Parent's dotted id; children are ``prefix.1``, ``prefix.2``.
        offset: Position of ``body`` within the whole markdown.
        page_index: Output of ``build_page_index``.
        pdf_name: Recorded in each node's ``source``.

    Returns:
        Nodes with ``id``, ``heading``, ``content``, ``source`` and
        ``subsections``.
    """
    level = first_heading_level(body, min_level)
    if level is None:
        return []

    nodes: list[dict] = []
    for i, (heading, child_body, head_start, body_start) in enumerate(
        split_on_level(body, level), start=1
    ):
        node_id = f"{id_prefix}.{i}" if id_prefix else str(i)
        abs_head = offset + head_start
        abs_body = offset + body_start
        abs_end = abs_body + len(child_body)

        next_level = first_heading_level(child_body, level + 1)
        page_start, page_end = page_range(page_index, abs_head, abs_end)
        node: dict = {
            "id": node_id,
            "heading": strip_markup(heading),
            "content": clean_content(direct_content(child_body, next_level)),
            "source": {
                "pdf": pdf_name,
                "page_start": page_start,
                "page_end": page_end,
                "char_start": abs_head,
                "char_end": abs_end,
            },
        }
        node["subsections"] = build_nodes(
            child_body, level + 1, node_id, abs_body, page_index, pdf_name
        )
        nodes.append(node)
    return nodes


def build_tree(markdown: str, page_index: list[tuple[int, int]], pdf_name: str) -> list[dict]:
    """The full section tree; see ``build_nodes``."""
    return build_nodes(markdown, 1, "", 0, page_index, pdf_name)


# ---------------------------------------------------------------------------
# Sub-entry extraction (traits, features, spell fields, item effects)
# ---------------------------------------------------------------------------

_NAMED_ENTRY_RE = re.compile(r"\*\*_\s*(.+?)\s*_\*\*\s*")
_BOLD_ENTRY_RE = re.compile(r"^\*\*(.+?)\.\*\*\s*", re.MULTILINE)


def parse_named_entries(content: str) -> tuple[str, list[dict]]:
    """
    Split prose into named entries.

    Entries open with a bold-italic run (``**_Multiattack._**``), or failing
    any, a bold run at line start (``**Casting Time.**``).

    Args:
        content: Section markdown.

    Returns:
        ``(preamble, entries)``; entries are ``{"name", "description"}``.
    """
    matches = list(_NAMED_ENTRY_RE.finditer(content))
    if not matches:
        matches = list(_BOLD_ENTRY_RE.finditer(content))
    if not matches:
        return content.strip(), []

    preamble = content[: matches[0].start()].strip()
    entries = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        name = m.group(1).strip().rstrip(".:")
        description = content[m.end():end].strip().lstrip(".").strip()
        if name and description:
            entries.append({"name": name, "description": description})
    return preamble, entries


# ---------------------------------------------------------------------------
# Spell and magic item metadata
# ---------------------------------------------------------------------------

_SPELL_SUBTITLE_RE = re.compile(
    r"^_?(?:Level\s+(\d+)\s+(\w+)|(\w+)\s+Cantrip)(?:\s*\(([^)]+)\))?_?",
    re.IGNORECASE,
)

MAGIC_ITEM_CATEGORIES = (
    "weapon", "armor", "wondrous item", "ring", "rod", "scroll", "staff",
    "wand", "potion", "ammunition",
)

RARITIES = ("Very Rare", "Rarity Varies", "Uncommon", "Common", "Rare",
            "Legendary", "Artifact")


def parse_spell_subtitle(text: str) -> dict | None:
    """
    Args:
        text: e.g. ``Level 5 Abjuration (Druid)`` or ``Evocation Cantrip``.

    Returns:
        ``{"level", "school", "classes"}`` with cantrips at level 0; None if
        the text is not a spell subtitle.
    """
    m = _SPELL_SUBTITLE_RE.match(strip_markup(text).strip())
    if not m:
        return None
    level = int(m.group(1)) if m.group(1) else 0
    school = (m.group(2) or m.group(3) or "").strip()
    classes = [c.strip() for c in m.group(4).split(",")] if m.group(4) else []
    return {"level": level, "school": school, "classes": classes}


# The book writes "Component:" as often as "Components:".
_SPELL_FIELD_RE = re.compile(
    r"\*\*(Casting Time|Range|Components?|Duration):\*\*\s*(.*?)"
    r"(?=\s*\*\*(?:Casting Time|Range|Components?|Duration):\*\*|\n\n|\Z)",
    re.DOTALL,
)
_MATERIAL_RE = re.compile(r"M\s*\(([^)]*)\)", re.IGNORECASE)
# Usually "worth 100+ GP"; Create Undead has "one 150+ GP black onyx stone".
_MATERIAL_COST_RE = re.compile(r"(?:worth\s+)?([\d,]+)\+?\s*GP", re.IGNORECASE)


def parse_spell_fields(content: str) -> dict:
    """
    Extract a spell's casting time, range, components and duration.

    Args:
        content: The spell section's markdown.

    Returns:
        The fields found, plus ``ritual`` (split off "Action or Ritual") and
        ``concentration`` (split off "Concentration, up to 1 minute").
    """
    fields = {
        m.group(1).lower().rstrip("s") if m.group(1).startswith("Component")
        else m.group(1).lower().replace(" ", "_"): " ".join(m.group(2).split())
        for m in _SPELL_FIELD_RE.finditer(content)
    }

    out: dict = {}
    casting_time = fields.get("casting_time")
    if casting_time:
        out["ritual"] = bool(re.search(r"\bor Ritual\b", casting_time, re.I))
        out["casting_time"] = re.sub(r"\s*or Ritual\b", "", casting_time, flags=re.I).strip()

    if "range" in fields:
        out["range"] = fields["range"]

    if "component" in fields:
        raw = fields["component"]
        material = _MATERIAL_RE.search(raw)
        # "V, S, M (a bit of fleece)"
        letters = {p.strip().upper() for p in raw.split("(")[0].split(",")}
        components: dict = {
            "verbal": "V" in letters,
            "somatic": "S" in letters,
            "material": material.group(1).strip() if material else None,
        }
        if material:
            cost = _MATERIAL_COST_RE.search(material.group(1))
            components["material_cost_gp"] = (
                int(cost.group(1).replace(",", "")) if cost else None
            )
            components["material_consumed"] = bool(
                re.search(r"consume", material.group(1), re.IGNORECASE)
            )
        out["components"] = components
        out["components_printed"] = raw

    duration = fields.get("duration")
    if duration:
        concentration = duration.lower().startswith("concentration")
        out["concentration"] = concentration
        out["duration"] = (
            re.sub(r"^Concentration,\s*", "", duration, flags=re.I).strip()
            if concentration else duration
        )
    return out


def parse_item_subtitle(text: str) -> dict | None:
    """
    Args:
        text: e.g. ``Weapon (Any Sword), Rare (Requires Attunement)``.

    Returns:
        ``{"category", "subtype", "rarity", "requires_attunement",
        "attunement_requirement"}``; None unless the text starts with a
        magic item category.
    """
    text = strip_markup(text).strip()
    if not any(text.lower().startswith(c) for c in MAGIC_ITEM_CATEGORIES):
        return None

    attunement = re.search(r"\(Requires Attunement(?:\s+by\s+([^)]+))?\)", text, re.I)
    if attunement:
        requirement = attunement.group(1).strip() if attunement.group(1) else None
        text = (text[: attunement.start()] + text[attunement.end():]).strip().rstrip(",")
    else:
        requirement = None

    m = re.match(r"^([A-Za-z ]+?)(?:\s*\(([^)]+)\))?(?:,\s*(.*))?$", text.strip())
    category = (m.group(1) if m else text).strip()
    subtype = m.group(2).strip() if m and m.group(2) else None
    tail = m.group(3).strip() if m and m.group(3) else text

    rarity = next((r for r in RARITIES if re.search(rf"\b{r}\b", tail, re.I)), None)
    return {
        "category": category,
        "subtype": subtype,
        "rarity": rarity,
        "requires_attunement": attunement is not None,
        "attunement_requirement": requirement,
    }


def leading_subtitle(content: str) -> str | None:
    """The first paragraph, if it is a single italic run; else None."""
    m = re.match(r"^\s*_([^_\n]+)_\s*$", content.split("\n\n")[0].strip())
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Annotation pass
# ---------------------------------------------------------------------------

def walk(nodes: list[dict]):
    """Yield every node in the tree, depth first."""
    for node in nodes:
        yield node
        yield from walk(node["subsections"])


def annotate(tree: list[dict], creatures: list[dict]) -> None:
    """
    Type every section, attach stat blocks and split out named entries.

    Args:
        tree: The section tree; mutated.
        creatures: Stat block records, matched by ``source.char_start``.
    """
    for section in tree:
        _annotate_subtree(section, "front_matter"
                          if section["heading"] in FRONT_MATTER else "rule")

    _attach_creatures(tree, creatures)
    _mark_groups(tree)
    _type_entry_sets(tree)


def _type_entry_sets(siblings: list[dict]) -> None:
    """
    Type the entries under each ``ENTRY_SET_ENTITY_TYPES`` heading.

    A heading with children types them; one without types its following
    siblings, because "Example Contagions" is printed at the same level as
    the contagions it introduces.
    """
    for index, node in enumerate(siblings):
        kind = ENTRY_SET_ENTITY_TYPES.get(node["heading"])
        if kind:
            for entry in node["subsections"] or siblings[index + 1:]:
                entry["entity_type"] = kind
        _type_entry_sets(node["subsections"])


def _attach_creatures(tree: list[dict], creatures: list[dict]) -> None:
    """
    Append each creature's name to ``creatures`` on its deepest containing
    section, by character offset.

    Not by name: a summoned creature shares no name with the spell section it
    is printed in.
    """
    for record in creatures:
        start = record["source"].get("char_start")
        if start is None:
            continue
        node = _deepest_containing(tree, start)
        if node is None:
            continue
        node.setdefault("creatures", []).append(record["name"])


def _deepest_containing(nodes: list[dict], offset: int) -> dict | None:
    for node in nodes:
        if node["source"]["char_start"] <= offset < node["source"]["char_end"]:
            return _deepest_containing(node["subsections"], offset) or node
    return None


def _annotate_subtree(node: dict, default: str) -> None:
    """
    Type a subtree: ``default``, or ``spell`` / ``magic_item`` where the
    section opens with that kind of subtitle.  Position alone never makes a
    spell, so a table inside a spell ("Teleportation Outcome") stays
    ``default``.
    """
    node["entity_type"] = default

    subtitle = leading_subtitle(node["content"])
    if subtitle:
        spell = parse_spell_subtitle(subtitle)
        if spell:
            node["spell"] = (spell | parse_spell_fields(node["content"])
                             | parse_spell_mechanics(node["content"]))
            node["entity_type"] = "spell"
        item = parse_item_subtitle(subtitle)
        if item:
            node["item"] = item
            node["entity_type"] = "magic_item"

    preamble, entries = parse_named_entries(node["content"])
    if entries:
        node["preamble"] = preamble
        node["entries"] = entries

    for child in node["subsections"]:
        _annotate_subtree(child, default)


def _mark_groups(tree: list[dict]) -> None:
    """
    Mark ``creature`` and ``creature_group`` sections.

    A section is a creature only when it owns exactly one stat block of the
    same name ("Azer" holding only "Azer Sentinel" is a group).  Within
    ``MONSTER_CHAPTERS``, any other section with stat blocks in its subtree
    is a group, with ``members``.
    """
    for chapter in tree:
        _mark_chapter(chapter, grouped=chapter["heading"] in MONSTER_CHAPTERS)


def _mark_chapter(chapter: dict, grouped: bool) -> None:
    """``_mark_groups`` for one top-level section, not counting the chapter."""
    for node in walk(chapter["subsections"]):
        owned = node.get("creatures", [])
        if len(owned) == 1 and owned[0] == node["heading"]:
            node["entity_type"] = "creature"
            continue

        members = sorted(set(owned) | {
            name for child in walk(node["subsections"])
            for name in child.get("creatures", [])
        })
        if members and grouped:
            node["entity_type"] = "creature_group"
            node["members"] = members


def type_from_records(nodes: list[dict], classes: list[dict],
                      origins: list[dict], feats: list[dict],
                      equipment: list[dict]) -> None:
    """
    Type each section an extracted record names as that record's kind.

    The records are found by the book's own structure (a class's "Level N:"
    features, a feat under its category heading), so they are evidence
    independent of where a section sits.  Only ``rule`` sections are
    retyped; a subtitle or stat block has already said what the rest are.

    Args:
        nodes: Every section; mutated.
        classes: From ``extract_classes``: the class and subclass sections
            become ``class`` and ``subclass``, their features
            ``class_feature``.
        origins: Species and backgrounds; their sections become ``origin``.
        feats: Their sections become ``feat``.
        equipment: Records with a ``section_id`` (gear, poisons) make it
            ``equipment``.
    """
    by_id = {node["id"]: node for node in nodes}

    def mark(section_id: str | None, kind: str) -> None:
        node = by_id.get(section_id)
        if node and node["entity_type"] == "rule":
            node["entity_type"] = kind

    for klass in classes:
        mark(klass["section_id"], "class")
        for feature in klass["features"]:
            mark(feature["section_id"], "class_feature")
        for subclass in klass["subclasses"]:
            mark(subclass["section_id"], "subclass")
            for feature in subclass.get("features", []):
                mark(feature["section_id"], "class_feature")
    for record in origins:
        mark(record["section_id"], "origin")
    for record in feats:
        mark(record["section_id"], "feat")
    for record in equipment:
        mark(record.get("section_id"), "equipment")


# ---------------------------------------------------------------------------
# Validation against the book's own index
# ---------------------------------------------------------------------------

_INDEX_ENTRY_RE = re.compile(r"([A-Za-z][A-Za-z’'\- ]*?)\.{3,}\s*(\d+)")


def parse_stat_block_index(tree: list[dict]) -> dict[str, int]:
    """
    Read the "Index of Stat Blocks" section.

    Entries pointing before the first monster section are table-of-contents
    lines from the shared page, and are dropped.

    Args:
        tree: The section tree.

    Returns:
        Creature name to page number.
    """
    node = next((n for n in tree if n["heading"] == "Index of Stat Blocks"), None)
    if not node:
        return {}
    first_monster_page = min(
        (n["source"]["page_start"] for n in tree
         if n["heading"] in ("Monsters", "Monsters A–Z", "Animals")),
        default=0,
    )
    return {
        m.group(1).strip(): int(m.group(2))
        for m in _INDEX_ENTRY_RE.finditer(node["content"])
        if int(m.group(2)) >= first_monster_page
    }


def section_boxes(anchors: list[dict], char_start: int, char_end: int) -> list[dict]:
    """
    The page rectangles a character range covers.

    Args:
        anchors: The anchors file, in document order.
        char_start: Start of the range in the markdown.
        char_end: End of the range, exclusive.

    Returns:
        The boxes of every anchor overlapping the range.
    """
    starts = [anchor["start"] for anchor in anchors]
    index = max(0, bisect.bisect_left(starts, char_start) - 1)
    boxes = []
    while index < len(anchors) and anchors[index]["start"] < char_end:
        if anchors[index]["end"] > char_start:
            boxes.extend(anchors[index]["boxes"])
        index += 1
    return boxes


def check_anchors(tree: list[dict], anchors: list[dict]) -> dict:
    """
    Check every section's boxes fall within its claimed page range.

    The range comes from page markers and the boxes from the lines, so they
    are independent.

    Returns:
        ``anchor_parts``, plus the ids of ``sections_without_geometry`` and
        the details of ``sections_with_misplaced_geometry``.
    """
    without, misplaced = [], []
    for node in walk(tree):
        source = node["source"]
        boxes = section_boxes(anchors, source["char_start"], source["char_end"])
        if not boxes:
            without.append(node["id"])
            continue
        pages = {box["page"] for box in boxes}
        if min(pages) < source["page_start"] or max(pages) > source["page_end"]:
            misplaced.append({"id": node["id"], "heading": node["heading"],
                              "pages": sorted(pages),
                              "claimed": [source["page_start"],
                                          source["page_end"]]})
    return {
        "anchor_parts": len(anchors),
        "sections_without_geometry": without,
        "sections_with_misplaced_geometry": misplaced,
    }


def validate(creatures: list[dict], index: dict[str, int]) -> dict:
    """
    Reconcile extracted stat blocks with the book's index of them.

    Args:
        creatures: Extracted stat block records.
        index: Output of ``parse_stat_block_index``.

    Returns:
        Missing, unexpected, misplaced (by more than one page) and duplicate
        names, every stat block warning, and ``check_mechanics``'s results.
    """
    extracted = {r["name"]: r["source"]["page_start"] for r in creatures}
    duplicates = sorted({r["name"] for r in creatures
                         if sum(1 for x in creatures if x["name"] == r["name"]) > 1})

    missing = sorted(name for name in index if name not in extracted)
    unexpected = sorted(name for name in extracted if name not in index)
    # A card starting at the foot of a column may be indexed to the next page.
    misplaced = [
        {"name": name, "index_page": page, "found_page": extracted[name]}
        for name, page in sorted(index.items())
        if name in extracted and abs(extracted[name] - page) > 1
    ]

    warnings = [
        {"creature": r["name"], "page": r["source"]["page_start"], "warnings": r["warnings"]}
        for r in creatures if r["warnings"]
    ]
    mechanics = check_mechanics(creatures)
    return {
        "index_entries": len(index),
        "stat_blocks_extracted": len(creatures),
        "missing_from_extraction": missing,
        "not_in_index": unexpected,
        "page_mismatches": misplaced,
        "duplicate_names": duplicates,
        "stat_block_warnings": warnings,
        **mechanics,
    }


# ---------------------------------------------------------------------------
# Mechanics checks
# ---------------------------------------------------------------------------

CREATURE_PARTS = ("traits", "actions", "bonus_actions", "reactions", "legendary_actions")


def check_mechanics(creatures: list[dict]) -> dict:
    """
    Check damage averages against their dice, and attack bonuses against
    ability modifier + proficiency bonus.

    Attacks with a parenthesised note are skipped; their bonus is not the
    plain sum.

    Returns:
        Counts checked and the mismatches for each.
    """
    damage_checked, damage_bad, bonus_checked, bonus_bad = 0, [], 0, []

    for creature in creatures:
        abilities = creature.get("abilities") or {}
        pb = creature.get("proficiency_bonus")
        for part in CREATURE_PARTS:
            for entry in creature.get(part, []):
                for damage in entry.get("damage", []):
                    if damage["average"] is None:
                        continue
                    damage_checked += 1
                    if average_hp(damage["dice"]) != damage["average"]:
                        damage_bad.append(f"{creature['name']}/{entry['name']}: "
                                          f"{damage['average']} vs {damage['dice']}")
                attack = entry.get("attack")
                if not attack or "note" in attack or not abilities or not pb:
                    continue
                bonus_checked += 1
                if attack["bonus"] not in {v["modifier"] + pb for v in abilities.values()}:
                    bonus_bad.append(f"{creature['name']}/{entry['name']}: {attack['bonus']:+d}")

    return {
        "damage_averages_checked": damage_checked,
        "damage_average_mismatches": damage_bad,
        "attack_bonuses_checked": bonus_checked,
        "attack_bonus_mismatches": bonus_bad,
    }


def count_nodes(nodes: list[dict]) -> int:
    """Nodes in the tree, descendants included."""
    return sum(1 + count_nodes(n["subsections"]) for n in nodes)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def parse(pdf_path: Path, markdown_path: Path,
          report: Callable[[str], None] = lambda _: None) -> dict:
    """
    Run the whole pipeline.

    Args:
        pdf_path: The SRD PDF.
        markdown_path: Where to write the markdown.  The anchors file is
            written beside it.
        report: Receives progress lines.

    Returns:
        The finished document, not yet written.
    """
    report(f"Extracting layout  ({pdf_path.name}) …")
    lines: list[Line] = extract_lines(pdf_path)
    pages = max(l.page for l in lines)
    report(f"  {len(lines)} lines over {pages} pages.")

    markdown, offsets, anchors = lines_to_markdown(lines)
    markdown_path.write_text(markdown, encoding="utf-8")
    report(f"  markdown → {markdown_path}")

    # Kept out of the document: nested per-line geometry that the graph
    # mapper would reject and nothing traverses.
    anchor_path = anchors_path_for(markdown_path)
    anchor_path.write_text(json.dumps(anchors), encoding="utf-8")
    report(f"  line anchors → {anchor_path} ({len(anchors)} parts)")

    report("Extracting stat blocks …")
    creatures = extract_stat_blocks(lines, pdf_path.name, offsets)
    report(f"  {len(creatures)} stat blocks.")

    report("Parsing stat block mechanics …")
    annotated = annotate_creatures(creatures)
    report(f"  {annotated} entries with structured mechanics.")

    report("Building hierarchy …")
    page_index = build_page_index(markdown)
    tree = build_tree(markdown, page_index, pdf_path.name)

    report("Typing entities …")
    annotate(tree, creatures)

    report("Extracting equipment …")
    nodes = list(walk(tree))
    gear = next((n for n in nodes if n["heading"] == "Adventuring Gear"), None)
    equipment = extract_equipment(nodes, gear["subsections"] if gear else [])
    report(f"  {len(equipment)} items.")

    report("Extracting character options …")
    classes = extract_classes(tree)
    species = extract_species(nodes)
    backgrounds = extract_backgrounds(nodes)
    feats = extract_feats(nodes)
    equipment += extract_poisons(nodes)
    report(f"  {len(classes)} classes, {len(species)} species, "
           f"{len(backgrounds)} backgrounds, {len(feats)} feats.")
    type_from_records(nodes, classes, species + backgrounds, feats, equipment)

    report("Reading the rules glossary …")
    mark_glossary_nodes(nodes)
    glossary = (extract_glossary(nodes) + extract_damage_types(nodes)
                + extract_poison_types(nodes))
    report(f"  {len(glossary)} terms.")

    report("Resolving cross-references …")
    references = extract_references(nodes, creatures, equipment, glossary)
    report(f"  {len(references)} edges.")

    report("Validating against the index of stat blocks …")
    validation = validate(creatures, parse_stat_block_index(tree))
    validation |= check_anchors(tree, anchors)

    types: dict[str, int] = {}
    for node in walk(tree):
        types[node["entity_type"]] = types.get(node["entity_type"], 0) + 1

    return {
        "meta": {
            "pdf": pdf_path.name,
            "pages": pages,
            "generated": date.today().isoformat(),
            "markdown": markdown_path.name,
            "counts": {
                "sections": count_nodes(tree),
                "creatures": len(creatures),
                "equipment": len(equipment),
                "classes": len(classes),
                "species": len(species),
                "backgrounds": len(backgrounds),
                "feats": len(feats),
                "glossary": len(glossary),
                "references": len(references),
                "entity_types": dict(sorted(types.items())),
            },
        },
        "sections": tree,
        "creatures": creatures,
        "equipment": equipment,
        "classes": classes,
        "species": species,
        "backgrounds": backgrounds,
        "feats": feats,
        "glossary": glossary,
        "references": references,
        "validation": validation,
    }


def build(pdf_path: Path | None = None, out_path: Path | None = None,
          markdown_path: Path | None = None,
          report: Callable[[str], None] = lambda _: None) -> dict:
    """
    Parse the SRD and write the JSON document, with its markdown beside it.

    Args:
        pdf_path: Defaults to ``settings.pdf_path``.
        out_path: Defaults to ``settings.output_path``.
        markdown_path: Defaults to ``out_path`` with a ``.md`` suffix.
        report: Receives progress lines.

    Returns:
        The document that was written.

    Raises:
        FileNotFoundError: The PDF does not exist.
    """
    settings = get_settings()
    pdf_path = pdf_path or settings.pdf_path
    out_path = out_path or settings.output_path
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    markdown_path = markdown_path or markdown_path_for(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    document = parse(pdf_path, markdown_path, report)
    out_path.write_text(json.dumps(document, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return document


def load(out_path: Path | None = None) -> dict:
    """
    Read a document the pipeline wrote earlier.

    Args:
        out_path: Defaults to ``settings.output_path``.

    Returns:
        The parsed document.

    Raises:
        FileNotFoundError: Nothing has been written there.
    """
    out_path = out_path or get_settings().output_path
    return json.loads(out_path.read_text(encoding="utf-8"))


def main() -> None:
    """``srd-parse``: build the artifact and print a validation summary."""
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Parse the SRD PDF into the JSON artifact.")
    parser.add_argument("--pdf", type=Path, default=settings.pdf_path)
    parser.add_argument("--out", type=Path, default=settings.output_path)
    parser.add_argument("--markdown", type=Path, default=None,
                        help="where to write the intermediate markdown "
                             "(default: alongside --out)")
    args = parser.parse_args()

    try:
        document = build(args.pdf, args.out, args.markdown, report=print)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    meta, validation = document["meta"], document["validation"]
    print()
    print(f"Saved {meta['counts']['sections']} sections, "
          f"{meta['counts']['creatures']} creatures, "
          f"{meta['counts']['equipment']} items, "
          f"{meta['counts']['glossary']} glossary terms and "
          f"{meta['counts']['references']} references → {args.out}")
    print()
    print("--- Entity types ---")
    for kind, n in meta["counts"]["entity_types"].items():
        print(f"  {kind:<16} {n:>5}")

    print()
    print("--- Validation ---")
    print(f"  index entries              {validation['index_entries']:>5}")
    print(f"  stat blocks extracted      {validation['stat_blocks_extracted']:>5}")
    print(f"  damage averages checked     {validation['damage_averages_checked']:>5}"
          f"  mismatches: {len(validation['damage_average_mismatches'])}")
    print(f"  attack bonuses checked      {validation['attack_bonuses_checked']:>5}"
          f"  mismatches: {len(validation['attack_bonus_mismatches'])}")
    for key in ("missing_from_extraction", "not_in_index", "page_mismatches",
                "duplicate_names"):
        values = validation[key]
        print(f"  {key.replace('_', ' '):<26} {len(values):>5}"
              + (f"  {values[:6]}" if values else ""))
    print(f"  sections without geometry  "
          f"{len(validation['sections_without_geometry']):>5}"
          f"  misplaced: {len(validation['sections_with_misplaced_geometry'])}")
    if validation["stat_block_warnings"]:
        print(f"  stat blocks with warnings  {len(validation['stat_block_warnings']):>5}")
        for w in validation["stat_block_warnings"]:
            print(f"    p{w['page']:>3}  {w['creature']}: {'; '.join(w['warnings'])}")

    print()
    print("--- Top-level sections ---")
    for node in document["sections"]:
        s = node["source"]
        print(f"  [{node['id']:>3}]  {node['heading']:<24}"
              f"  pp.{s['page_start']:>3}–{s['page_end']:<3}"
              f"  {count_nodes(node['subsections']):>4} descendants")


if __name__ == "__main__":
    main()
