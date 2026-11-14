"""The book checks itself: wherever it says one thing twice, both readings must agree.

The Contents and Index of Stat Blocks (pages 2 to 4) say what is printed on
which page; class spell lists repeat each spell's subtitle; a class's
features table names its feature headings; the Adventuring Gear table names
the gear described after it; the Weapons table names properties and
masteries defined above it. Each pair is read independently, so a defect in
either shows as a disagreement.
"""

from __future__ import annotations

import re
from itertools import pairwise

from dnd_graph_rag.srd.model import (
    Block,
    Contents,
    Heading,
    Paragraph,
    Section,
    StatBlock,
    Table,
    plain,
)
from dnd_graph_rag.srd.sections import walk_paths

CONTENTS = "Contents"
INDEX = "Index of Stat Blocks"
# Disagreements printed in the book itself (CLAUDE.md, "Known source-document
# quirks"): reported, never failed on.
KNOWN = frozenset({
    *(f"Spells: Flaming Sphere is Level 2 Conjuration, the {c} list says Level 2 Evocation"
      for c in ("Druid", "Sorcerer", "Wizard")),
    "Spells: Mind Spike names Sorcerer, which does not list it",
    *(f"Spells: Phantasmal Force names {c}, which does not list it"
      for c in ("Bard", "Sorcerer", "Wizard")),
})
# "Level 2 Evocation (Wizard)", "Evocation Cantrip (Sorcerer, Wizard)".
_SPELL = re.compile(r"^(?:Level (?P<level>\d) (?P<school>\w+)|(?P<cantrip>\w+) Cantrip) \((?P<classes>[^)]*)\)$")
# "Cantrips (Level 0 Bard Spells)", "Level 1 Bard Spells".
_SPELL_LIST = re.compile(r"^(?:Cantrips \(Level 0 (?P<cantrips>\w+) Spells\)|Level (?P<level>\d) (?P<cls>\w+) Spells)$")
# "Level 2: Reckless Attack".
_FEATURE = re.compile(r"^Level (?P<level>\d+): (?P<name>.*)$")
# A note after a name: "Action Surge (one use)", "Thrown (Range 20/60)".
_NOTE = re.compile(r" \(.*\)$")


def problems(blocks: list[Block], sections: list[Section]) -> list[str]:
    """Every way the blocks and sections disagree with what the book says elsewhere.

    Args:
        blocks: The book's blocks in reading order, as ``read_blocks`` returns them.
        sections: Those blocks as a tree, as ``build_sections`` returns them.

    Returns:
        One message per disagreement; empty when the book agrees with itself.

    Raises:
        ValueError: A list or table a check reads is missing.
    """
    return (check_contents(sections, listed(blocks, CONTENTS)) + check_index(blocks, listed(blocks, INDEX))
            + check_spells(blocks) + check_classes(blocks) + check_gear(blocks) + check_weapons(blocks))


def listed(blocks: list[Block], title: str) -> Contents:
    """The entries printed under the heading ``title``."""
    for block, after in pairwise(blocks):
        if isinstance(block, Heading) and block.text == title and isinstance(after, Contents):
            return after
    raise ValueError(f"no {title} list")


def check_contents(sections: list[Section], contents: Contents) -> list[str]:
    """Each Contents entry is a section on its page, in book order, under its entry's parent.

    An entry nests under the last entry above it of a lower level, and its
    section must be inside that entry's section. Levels themselves are not
    compared: the Contents skips them ("Acolyte", a level 4 heading, is
    listed under level 2 "Character Backgrounds"). Every chapter is listed,
    except the lists' own.
    """
    ordered = list(walk_paths(sections))
    found: list[str] = []
    at = 0
    parents: list[tuple[int, Section]] = []   # (contents level, its section)
    for entry in contents.entries:
        name = plain(entry.runs)
        match = next((i for i in range(at, len(ordered))
                      if (ordered[i][0].heading, ordered[i][0].source.page_start) == (name, entry.page)), None)
        if match is None:
            found.append(f"Contents: {name} (p. {entry.page}) has no section on that page after the last match")
            continue
        at = match + 1
        section, path = ordered[match]
        while parents and parents[-1][0] >= entry.level:
            parents.pop()
        if parents and not any(ancestor is parents[-1][1] for ancestor in path):
            found.append(f"Contents: {name} (p. {entry.page}) is not under {parents[-1][1].heading}")
        parents.append((entry.level, section))
    chapters = {(plain(e.runs), e.page) for e in contents.entries if e.level == 1}
    found += [f"Contents: chapter {s.heading} (p. {s.source.page_start}) is not listed" for s in sections
              if s.source.page_start not in contents.pages and (s.heading, s.source.page_start) not in chapters]
    return found


def check_index(blocks: list[Block], index: Contents) -> list[str]:
    """The Index of Stat Blocks names exactly the stat blocks from its first page on.

    Stat blocks printed earlier, in spells and magic items (Giant Fly,
    Avatar of Death, ...), are not indexed.
    """
    first = min(e.page for e in index.entries)
    printed = {(b.name, b.pages[0]) for b in blocks if isinstance(b, StatBlock) and b.pages[0] >= first}
    entries = [(plain(e.runs), e.page) for e in index.entries]
    found = [f"Index: {name} (p. {page}) has no stat block on that page"
             for name, page in entries if (name, page) not in printed]
    found += [f"Index: stat block {name} (p. {page}) is not listed"
              for name, page in sorted(printed - set(entries))]
    found += [f"Index: {name} (p. {page}) is listed twice"
              for name, page in sorted(set(entries)) if entries.count((name, page)) > 1]
    return found


def check_spells(blocks: list[Block]) -> list[str]:
    """Each spell's subtitle agrees with every class spell list, and each listed spell is described.

    A spell is a heading under "Spell Descriptions" with its subtitle below it.
    """
    described: dict[str, tuple[int, str, list[str]]] = {}
    found: list[str] = []
    for block, after in pairwise(under(blocks, "Spell Descriptions")):
        if isinstance(block, Heading):
            match = _SPELL.match(plain(after.runs)) if isinstance(after, Paragraph) else None
            if match is None:
                found.append(f"Spells: {block.text} (p. {block.page}) has no spell subtitle")
                continue
            described[block.text] = (int(match["level"] or 0), match["school"] or match["cantrip"],
                                     [c.strip() for c in match["classes"].split(",")])
    lists: dict[str, list[tuple[str, int, str]]] = {}   # spell: (class, level, school)
    for table in (b for b in blocks if isinstance(b, Table)):
        if match := _SPELL_LIST.match(plain(table.caption)):
            for row in table.rows:
                lists.setdefault(plain(row[0]), []).append(
                    (match["cantrips"] or match["cls"], int(match["level"] or 0), plain(row[1])))
    for spell in sorted(lists.keys() - described.keys()):
        found.append(f"Spells: {spell} is on a class list but not described")
    for spell, (level, school, classes) in sorted(described.items()):
        listing = {cls for cls, _, _ in lists.get(spell, [])}
        for cls, on_level, on_school in lists.get(spell, []):
            if (on_level, on_school) != (level, school):
                found.append(f"Spells: {spell} is {spell_kind(level, school)}, "
                             f"the {cls} list says {spell_kind(on_level, on_school)}")
        found += [f"Spells: {spell} names {cls}, which does not list it" for cls in classes
                  if cls not in listing]
        found += [f"Spells: the {cls} list has {spell}, whose subtitle does not name it"
                  for cls in sorted(listing - set(classes))]
    return found


def spell_kind(level: int, school: str) -> str:
    """"Level 2 Evocation" or "Evocation Cantrip", as subtitles print it."""
    return f"Level {level} {school}" if level else f"{school} Cantrip"


def check_classes(blocks: list[Block]) -> list[str]:
    """Each class's features table and its feature headings name the same features.

    The table names a repeated feature at every level ("Ability Score
    Improvement" at 4, 8, 12, ...) and the book describes it once, at the
    first; "Subclass feature" is a heading in the subclass at that level.
    """
    found: list[str] = []
    titles = [b.text for b in blocks if isinstance(b, Heading)]
    for name in (b.text for b in under(blocks, "Classes") if isinstance(b, Heading) and b.level == 2):
        features = feature_headings(under(blocks, f"{name} Class Features"))
        subclass = next(t for t in titles if t.startswith(f"{name} Subclass:"))
        subclass_levels = {level for level, _ in feature_headings(under(blocks, subclass))}
        listed_features: set[tuple[int, str]] = set()
        table = captioned(blocks, f"{name} Features")
        header = [plain(cell) for cell in table.header[-1]]
        for row in table.rows:
            level = int(re.sub(r"\D", "", plain(row[header.index("Level")])))
            for feature in plain(row[header.index("Class Features")]).split(", "):
                feature = _NOTE.sub("", feature)
                if feature == "\u2014":   # no feature at this level
                    continue
                listed_features.add((level, feature))
                if feature == "Subclass feature":
                    described = level in subclass_levels
                else:
                    described = any(n == feature and at <= level for at, n in features)
                if not described:
                    found.append(f"Classes: {name} level {level} {feature} has no heading")
        found += [f"Classes: {name} heading Level {level}: {feature} is not in its table"
                  for level, feature in sorted(features - listed_features)]
    return found


def feature_headings(blocks: list[Block]) -> set[tuple[int, str]]:
    """The (level, name) of each "Level N: Name" heading among ``blocks``."""
    return {(int(m["level"]), m["name"]) for b in blocks if isinstance(b, Heading)
            for m in [_FEATURE.match(b.text)] if m}


def check_gear(blocks: list[Block]) -> list[str]:
    """The Adventuring Gear table and the gear described after it name the same items at one price.

    A description heads "Acid (25 GP)"; one prices variants that are rows of
    their own: "Spell Scroll (Cantrip, 30 GP; Level 1, 50 GP)" covers the rows
    "Spell Scroll (Cantrip)" and "Spell Scroll (Level 1)".
    """
    prices: dict[str, str] = {}
    found: list[str] = []
    for heading in (b for b in under(blocks, "Adventuring Gear") if isinstance(b, Heading)):
        match = re.match(r"^(?P<name>.*) \((?P<price>.*)\)$", heading.text)
        if match is None:
            found.append(f"Gear: {heading.text} (p. {heading.page}) has no price")
            continue
        variants = [v.split(", ") for v in match["price"].split("; ")]
        if all(len(v) == 2 for v in variants):
            prices.update({f"{match['name']} ({variant})": price for variant, price in variants})
        else:
            prices[match["name"]] = match["price"]
    rows = {plain(row[0]): plain(row[-1]) for row in captioned(blocks, "Adventuring Gear").rows}
    found += [f"Gear: {item} is in the table but not described" for item in sorted(rows.keys() - prices.keys())]
    found += [f"Gear: {item} is described but not in the table" for item in sorted(prices.keys() - rows.keys())]
    found += [f"Gear: {item} costs {prices[item]}, the table says {rows[item]}"
              for item in sorted(rows.keys() & prices.keys()) if rows[item] != prices[item]]
    return found


def check_weapons(blocks: list[Block]) -> list[str]:
    """Every property and mastery in the Weapons table is defined under Properties or Mastery Properties."""
    defined = {b.text for b in under(blocks, "Properties") + under(blocks, "Mastery Properties")
               if isinstance(b, Heading)}
    found: list[str] = []
    for row in captioned(blocks, "Weapons").rows:
        weapon, _, properties, mastery = (plain(cell) for cell in row[:4])
        if not mastery:     # a category row ("Simple Melee Weapons")
            continue
        found += [f"Weapons: {weapon}'s {name} is not defined" for name in
                  [_NOTE.sub("", p) for p in properties.split(", ") if p != "\u2014"] + [mastery]
                  if name not in defined]
    return found


def under(blocks: list[Block], title: str) -> list[Block]:
    """The blocks after the heading ``title``, up to the next heading at its level or above."""
    start = next((i for i, b in enumerate(blocks) if isinstance(b, Heading) and b.text == title), None)
    if start is None:
        raise ValueError(f"no {title} heading")
    level = blocks[start].level
    end = next((i for i in range(start + 1, len(blocks))
                if isinstance(blocks[i], Heading) and blocks[i].level <= level), len(blocks))
    return blocks[start + 1:end]


def captioned(blocks: list[Block], caption: str) -> Table:
    """The table captioned ``caption``."""
    for block in blocks:
        if isinstance(block, Table) and plain(block.caption) == caption:
            return block
    raise ValueError(f"no {caption} table")
