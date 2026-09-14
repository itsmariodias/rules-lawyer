"""
Stage 1's last step: markdown to the finished JSON artifact.

``layout`` turns the PDF into ordered lines and markdown, ``statblocks``
turns those lines into creature records, and this module builds the section
hierarchy over the markdown, types every node, attaches the entities the
other modules extracted, and validates the lot against the book's own index::

    {
      "meta":       { pdf, pages, generated, counts },
      "sections":   [ nested section tree ],
      "creatures":  [ flat stat block records ],
      "validation": { index reconciliation and every warning raised }
    }

Sections and creatures are separate collections because a stat block is a
card in the book rather than a heading: several creatures can sit under one
heading, and a heading's name ("Black Dragons") is often a category. Section
nodes carry ``entity_type`` and, where they own stat blocks, ``creatures``.

The markdown is written next to the JSON, so every node's ``char_start`` and
``char_end`` resolves back to text.
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
# The top-level section a node lives under determines what kind of thing it
# is.  Where a section mixes kinds (Spells holds both the class spell lists
# and the spell descriptions) the rule keys off the intermediate heading too.

SECTION_ENTITY_TYPES: dict[str, str] = {
    "Legal Information": "front_matter",
    "Contents": "front_matter",
    "Index of Stat Blocks": "front_matter",
    "Playing the Game": "rule",
    "Character Creation": "rule",
    "Classes": "class_feature",
    "Character Origins": "origin",
    "Feats": "feat",
    "Equipment": "equipment",
    "Spells": "rule",
    "Rules Glossary": "rule",
    "Gameplay Toolbox": "rule",
    "Magic Items": "rule",
    # The monster sections default to lore: "creature" is earned by owning a
    # stat block, never by sitting under the Monsters heading.
    "Monsters": "rule",
    "Monsters A–Z": "creature_lore",
    "Animals": "creature_lore",
}

# (top-level section, second-level heading) → type for that subtree's leaves
SUBTREE_ENTITY_TYPES: list[tuple[str, str, str]] = [
    ("Spells", "Spell Descriptions", "spell"),
    ("Magic Items", "Magic Items A–Z", "magic_item"),
    ("Feats", "Feat Descriptions", "feat"),
]

# Headings that introduce a closed set of entries which are entities in their
# own right, not rules prose.  Without this they are indistinguishable from
# the chapters around them, so "which environmental effects deal Cold damage"
# has nothing to select on — even though the edges are already there.
ENTRY_SET_ENTITY_TYPES: dict[str, str] = {
    "Environmental Effects": "environmental_effect",
    "Example Traps": "trap",
    "Example Contagions": "contagion",
}


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def strip_markup(text: str) -> str:
    return _EMPHASIS_RE.sub(r"\1", text).replace("_", "").strip()


def clean_content(text: str) -> str:
    """Remove page markers and collapse the blank lines they leave behind."""
    text = _PAGE_MARKER_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def build_page_index(markdown: str) -> list[tuple[int, int]]:
    return [(m.start(), int(m.group(1))) for m in _PAGE_MARKER_RE.finditer(markdown)]


def page_at(page_index: list[tuple[int, int]], pos: int) -> int:
    offsets = [p[0] for p in page_index]
    idx = bisect.bisect_right(offsets, pos) - 1
    return page_index[idx][1] if idx >= 0 else 1


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------

# Level 6 is reserved for stat block sections ("Traits", "Actions").  Their
# content is already captured, split into named entries, on the creature
# records, so they stay part of their parent's prose instead of becoming
# hundreds of near-empty "Actions" nodes in the tree.
MAX_HEADING_LEVEL = 5


def first_heading_level(body: str, min_level: int) -> int | None:
    for level in range(min_level, MAX_HEADING_LEVEL + 1):
        if re.search(rf'^{"#" * level} ', body, re.MULTILINE):
            return level
    return None


def split_on_level(body: str, level: int) -> list[tuple[str, str, int, int]]:
    """Split a body on headings of exactly *level*."""
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
        node: dict = {
            "id": node_id,
            "heading": strip_markup(heading),
            "content": clean_content(direct_content(child_body, next_level)),
            "source": {
                "pdf": pdf_name,
                "page_start": page_at(page_index, abs_head),
                "page_end": page_at(page_index, abs_end),
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
    return build_nodes(markdown, 1, "", 0, page_index, pdf_name)


# ---------------------------------------------------------------------------
# Sub-entry extraction (traits, features, spell fields, item effects)
# ---------------------------------------------------------------------------

_NAMED_ENTRY_RE = re.compile(r"\*\*_\s*(.+?)\s*_\*\*\s*")
_BOLD_ENTRY_RE = re.compile(r"^\*\*(.+?)\.\*\*\s*", re.MULTILINE)


def parse_named_entries(content: str) -> tuple[str, list[dict]]:
    """
    Split prose into named entries, returning (preamble, entries).

    The SRD names a trait, feature or effect by leading its paragraph with a
    bold-italic run ("**_Multiattack._**") or a bold run ("**Casting Time:**").
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
    """``Level 5 Abjuration (Druid)`` → level, school and class list."""
    m = _SPELL_SUBTITLE_RE.match(strip_markup(text).strip())
    if not m:
        return None
    level = int(m.group(1)) if m.group(1) else 0
    school = (m.group(2) or m.group(3) or "").strip()
    classes = [c.strip() for c in m.group(4).split(",")] if m.group(4) else []
    return {"level": level, "school": school, "classes": classes}


# The four mechanical fields printed under a spell's subtitle.  The book
# writes "Component:" as often as "Components:" — accept both.
_SPELL_FIELD_RE = re.compile(
    r"\*\*(Casting Time|Range|Components?|Duration):\*\*\s*(.*?)"
    r"(?=\s*\*\*(?:Casting Time|Range|Components?|Duration):\*\*|\n\n|\Z)",
    re.DOTALL,
)
_MATERIAL_RE = re.compile(r"M\s*\(([^)]*)\)", re.IGNORECASE)
# Usually "a pearl worth 100+ GP", but sometimes the price leads the noun:
# "one 150+ GP black onyx stone for each corpse".
_MATERIAL_COST_RE = re.compile(r"(?:worth\s+)?([\d,]+)\+?\s*GP", re.IGNORECASE)


def parse_spell_fields(content: str) -> dict:
    """
    Extract a spell's casting time, range, components and duration.

    Concentration and Ritual are not printed as fields of their own — the
    book folds them into Duration ("Concentration, up to 1 minute") and
    Casting Time ("Action or Ritual") — so they are lifted out here, since
    both are properties a graph will want to filter on directly.
    """
    fields = {
        m.group(1).lower().rstrip("s") if m.group(1).startswith("Component")
        else m.group(1).lower().replace(" ", "_"): " ".join(m.group(2).split())
        for m in _SPELL_FIELD_RE.finditer(content)
    }

    out: dict = {}
    casting_time = fields.get("casting_time")
    if casting_time:
        # "Action or Ritual" — strip the marker, keep the time itself.
        out["ritual"] = bool(re.search(r"\bor Ritual\b", casting_time, re.I))
        out["casting_time"] = re.sub(r"\s*or Ritual\b", "", casting_time, flags=re.I).strip()

    if "range" in fields:
        out["range"] = fields["range"]

    if "component" in fields:
        raw = fields["component"]
        material = _MATERIAL_RE.search(raw)
        # Components are a comma-separated letter list, with the material's
        # description in parentheses after the M: "V, S, M (a bit of fleece)".
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
    """``Weapon (Any Sword), Rare (Requires Attunement)`` → its parts."""
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
    m = re.match(r"^\s*_([^_\n]+)_\s*$", content.split("\n\n")[0].strip())
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Annotation pass
# ---------------------------------------------------------------------------

def walk(nodes: list[dict]):
    for node in nodes:
        yield node
        yield from walk(node["subsections"])


def annotate(tree: list[dict], creatures: list[dict]) -> None:
    """Assign entity types, attach stat blocks and split out named entries."""
    for section in tree:
        section_name = section["heading"]
        default = SECTION_ENTITY_TYPES.get(section_name, "rule")
        _annotate_subtree(section, section_name, default)

    _attach_creatures(tree, creatures)
    _mark_groups(tree)
    _type_entry_sets(tree)


def _type_entry_sets(siblings: list[dict]) -> None:
    """
    Type the closed sets a heading introduces.

    The book does this two ways.  "Environmental Effects" and "Example Traps"
    nest their entries beneath them, the way "Sample Poisons" does; "Example
    Contagions" is printed as a plain sibling standing ahead of the three it
    introduces.  So a heading with children types those, and one without
    types the siblings that follow it.
    """
    for index, node in enumerate(siblings):
        kind = ENTRY_SET_ENTITY_TYPES.get(node["heading"])
        if kind:
            for entry in node["subsections"] or siblings[index + 1:]:
                entry["entity_type"] = kind
        _type_entry_sets(node["subsections"])


def _attach_creatures(tree: list[dict], creatures: list[dict]) -> None:
    """
    Attach every stat block to the section it was printed in.

    Matching is by character offset, not by name: a creature summoned by a
    spell ("Giant Insect" under Conjure Animals) shares no name with its
    section, and a name match alone would also let a heading and the stat
    block card beneath it both claim the same creature.
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


def _subtree_type(section: str, path: list[str], default: str) -> str:
    for top, second, kind in SUBTREE_ENTITY_TYPES:
        if section == top and second in path:
            return kind
    return default


def _annotate_subtree(node: dict, section: str, default: str,
                      path: list[str] | None = None) -> None:
    path = (path or []) + [node["heading"]]
    node["entity_type"] = _subtree_type(section, path, default)

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
        _annotate_subtree(child, section, default, path)


def _mark_groups(tree: list[dict]) -> None:
    """
    Separate a category heading from a creature heading.

    A heading is the creature only when it holds exactly one stat block and
    shares its name.  "Ghast" is a creature; "Black Dragons" holds four and
    is none of them, and "Azer" holds only "Azer Sentinel" — a category of
    one, not that creature.  Everything above them that contains creatures
    is a group too, so a graph can walk from "Monsters A–Z" downward.
    """
    for node in walk(tree):
        owned = node.get("creatures", [])
        if len(owned) == 1 and owned[0] == node["heading"]:
            node["entity_type"] = "creature"
            continue

        members = sorted(set(owned) | {
            name for child in walk(node["subsections"])
            for name in child.get("creatures", [])
        })
        if members:
            node["entity_type"] = "creature_group"
            node["members"] = members


# ---------------------------------------------------------------------------
# Validation against the book's own index
# ---------------------------------------------------------------------------

_INDEX_ENTRY_RE = re.compile(r"([A-Za-z][A-Za-z’'\- ]*?)\.{3,}\s*(\d+)")


def parse_stat_block_index(tree: list[dict]) -> dict[str, int]:
    """
    Read the "Index of Stat Blocks" section: creature name → page.

    The index shares its opening page with the table of contents, whose
    entries have the same dotted-leader shape.  Every stat block lives in the
    monster sections at the back of the book, so entries pointing anywhere
    earlier are contents lines that bled in and are dropped.
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

    Anchors are emitted in document order, so the run of parts that overlap
    the range is contiguous and can be found by bisecting for its start.
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
    Every section's geometry must fall on the pages the section claims.

    The page range and the rectangles are derived independently — one from
    the ``<!-- PAGE:n -->`` markers in the finished markdown, the other from
    the lines themselves — so agreeing is a real assertion that the offsets
    and the boxes describe the same passage.  A section with no geometry at
    all means a part was emitted that no line accounts for.
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
    Reconcile what we extracted against the book's own index of stat blocks.

    The index is an independent list of every creature and the page it is on,
    which makes it a free assertion that nothing was missed, duplicated or
    attributed to the wrong page.
    """
    extracted = {r["name"]: r["source"]["page_start"] for r in creatures}
    duplicates = sorted({r["name"] for r in creatures
                         if sum(1 for x in creatures if x["name"] == r["name"]) > 1})

    missing = sorted(name for name in index if name not in extracted)
    unexpected = sorted(name for name in extracted if name not in index)
    # One page of slack: a stat block that starts at the foot of a column can
    # be indexed to the page its card visually occupies.
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
# CLI
# ---------------------------------------------------------------------------

CREATURE_PARTS = ("traits", "actions", "bonus_actions", "reactions", "legendary_actions")


def check_mechanics(creatures: list[dict]) -> dict:
    """
    Cross-check the parsed mechanics against the arithmetic they must satisfy.

    A printed damage average has to equal the average of its own dice, and a
    monster's attack bonus has to be one of its ability modifiers plus its
    proficiency bonus.  Both are independent of how the text was parsed, so a
    disagreement means either the parse or the extraction beneath it is wrong.
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
    return sum(1 + count_nodes(n["subsections"]) for n in nodes)


def parse(pdf_path: Path, markdown_path: Path,
          report: Callable[[str], None] = lambda _: None) -> dict:
    """
    Run the whole pipeline and return the finished document.

    Progress goes to *report* rather than to stdout so the same function
    serves the command line and the API without one of them being noisy.
    """
    report(f"Extracting layout  ({pdf_path.name}) …")
    lines: list[Line] = extract_lines(pdf_path)
    pages = max(l.page for l in lines)
    report(f"  {len(lines)} lines over {pages} pages.")

    markdown, offsets, anchors = lines_to_markdown(lines)
    markdown_path.write_text(markdown, encoding="utf-8")
    report(f"  markdown → {markdown_path}")

    # Written beside the markdown rather than into the document: it is
    # per-line nested geometry, which is exactly the shape the graph mapper
    # rejects, and nothing traverses it.
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

    Missing paths are resolved from the settings here rather than defaulted
    at import time, so overriding an environment variable still takes effect.
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
    """Read a document the pipeline wrote earlier."""
    out_path = out_path or get_settings().output_path
    return json.loads(out_path.read_text(encoding="utf-8"))


def main() -> None:
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
