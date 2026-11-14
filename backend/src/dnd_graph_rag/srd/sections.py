"""Blocks to the section tree: headings open sections, floats become sections of their own."""

from __future__ import annotations

import re
from collections.abc import Iterator

from dnd_graph_rag.srd.model import (
    Block,
    Contents,
    Entry,
    Heading,
    Paragraph,
    Section,
    Sidebar,
    Source,
    StatBlock,
    Table,
    plain,
)

# The heading over the book's table of contents (page 2).
CONTENTS = "Contents"


def build_sections(blocks: list[Block]) -> list[Section]:
    """Nest the book's blocks into sections, in reading order.

    A heading opens a section, closing every open section at its level or
    deeper. Other blocks belong to the deepest open section. A float (a stat
    block, a captioned table or a sidebar) is a section of its own, holding
    only itself, one level below the section it is printed in and after that
    section's own blocks: a section's blocks come before its subsections, and
    33 floats are printed with more of their section's text after them. A
    float the book places elsewhere is then moved there (``place_floats``).

    Args:
        blocks: The book's blocks from ``read_blocks``, a heading first.

    Returns:
        The top-level sections, each with its dotted id and page range.

    Raises:
        ValueError: A block comes before the first heading.
    """
    roots: list[Section] = []
    open_sections: list[Section] = []
    for block in blocks:
        if isinstance(block, Heading):
            while open_sections and open_sections[-1].level >= block.level:
                open_sections.pop()
            section = Section("", block.text, block.level, [], [], Source(block.page, block.page),
                              boxes=block.boxes)
            (open_sections[-1].subsections if open_sections else roots).append(section)
            open_sections.append(section)
        elif not open_sections:
            raise ValueError(f"a {type(block).__name__} on page {block.pages[0]} has no heading above it")
        elif (heading := float_heading(block)) is not None:
            parent = open_sections[-1]
            parent.subsections.append(Section("", heading, min(parent.level + 1, 6),
                                              [block], [], Source(block.pages[0], block.pages[-1])))
        else:
            open_sections[-1].blocks.append(block)
    place_floats(roots)
    number(roots, "")
    for section in roots:
        set_pages(section)
    return roots


def place_floats(roots: list[Section]) -> None:
    """Move each float the book places elsewhere to the section it belongs to.

    The book prints a float where it fits, not where it belongs: the Weapons
    table follows Vex, the last mastery property, and Fiendish Legacies is
    printed under Human but named by Tiefling. A captioned table goes to the
    section naming it (``naming_section``), at the end of that section
    nearest where it is printed, counted in sections read: first if printed
    before it (Barbarian Features, before "Barbarian Class Features") or near
    its start (Ranger Features, in its first feature), last if printed near
    its end (Weapons, after Vex). A sidebar the Contents lists goes where it
    lists it (``listed_place``): "Running a Monster", printed in Resistances
    and Vulnerabilities, is listed under Monsters after Parts of a Stat
    Block. Any other float stays where it is printed.
    """
    order = {id(section): position for position, (section, _) in enumerate(walk_paths(roots))}
    contents = next((block for section in walk(roots) if section.heading == CONTENTS
                     for block in section.blocks if isinstance(block, Contents)), None)
    # float, printed in, owner, and the section it follows if the Contents says
    moves: list[tuple[Section, Section, Section, Section | None]] = []
    for section, path in walk_paths(roots):
        block = section.blocks[0] if len(section.blocks) == 1 else None
        owner, after = None, None
        if isinstance(block, Table) and block.caption:
            owner = naming_section(section.heading, path, order)
        elif isinstance(block, Sidebar) and contents is not None:
            owner, after = listed_place(section, contents, roots)
        if owner is not None and owner is not path[-1]:
            moves.append((section, path[-1], owner, after))
    last = {id(section): max(order[id(s)] for s, _ in depths(section, 0)) for section, _ in walk_paths(roots)}
    at_front: dict[int, int] = {}    # owner -> floats already put first in it, in book order
    for moved, printed, owner, after in moves:
        printed.subsections.remove(moved)
        if after is not None:
            owner.subsections.insert(owner.subsections.index(after) + 1, moved)
        elif order[id(printed)] - order[id(owner)] < last[id(owner)] - order[id(printed)]:
            owner.subsections.insert(at_front.get(id(owner), 0), moved)
            at_front[id(owner)] = at_front.get(id(owner), 0) + 1
        else:
            owner.subsections.append(moved)
        moved.level = min(owner.level + 1, 6)


def naming_section(name: str, path: list[Section], order: dict[int, int]) -> Section | None:
    """The section owning the table ``name``: the shallowest naming it in a paragraph.

    Looked for in the part of the book the table is printed in (the level 2
    section above it), the first of equals. A mention in a list is not
    ownership: "Gain all the traits in the Core Barbarian Traits table" names
    it in "As a Level 1 Character", and it stays with the class.
    """
    pattern = re.compile(rf"{re.escape(name)}\s+table", re.IGNORECASE)
    area = path[min(1, len(path) - 1)]
    owners = [(depth, order[id(section)], section) for section, depth in depths(area, path.index(area) + 1)
              if any(isinstance(block, Paragraph) and pattern.search(plain(block.runs))
                     for block in section.blocks)]
    return min(owners, key=lambda owner: owner[:2])[2] if owners else None


def listed_place(section: Section, contents: Contents,
                 roots: list[Section]) -> tuple[Section | None, Section | None]:
    """Where the Contents lists ``section``: the section of the entry it is under, and of
    the entry before it at its level (None if it is listed first); (None, None) if unlisted."""
    def found(entry: Entry) -> Section | None:
        return next((s for s in walk(roots) if (s.heading, s.source.page_start) == (plain(entry.runs), entry.page)),
                    None)

    entries = contents.entries
    for position, entry in enumerate(entries):
        if (plain(entry.runs), entry.page) == (section.heading, section.source.page_start):
            above = list(reversed(entries[:position]))
            parent = next((e for e in above if e.level < entry.level), None)
            if parent is None:
                return None, None
            sibling = next((e for e in above[:above.index(parent)] if e.level == entry.level), None)
            return found(parent), found(sibling) if sibling else None
    return None, None


def walk_paths(sections: list[Section], path: tuple[Section, ...] = ()) -> Iterator[tuple[Section, list[Section]]]:
    """Every section with its ancestors, root first, depth first."""
    for section in sections:
        yield section, list(path)
        yield from walk_paths(section.subsections, (*path, section))


def depths(section: Section, depth: int) -> Iterator[tuple[Section, int]]:
    """A section and everything under it, each with its depth (a root is 1)."""
    yield section, depth
    for child in section.subsections:
        yield from depths(child, depth + 1)





def walk(sections: list[Section]) -> Iterator[Section]:
    """Every section in the tree, depth first, each before its subsections."""
    for section in sections:
        yield section
        yield from walk(section.subsections)


def float_heading(block: Block) -> str | None:
    """The heading of the section a float makes: a stat block's name, a table's caption,
    a sidebar's title; None if the block is not a float."""
    if isinstance(block, StatBlock):
        return block.name
    if isinstance(block, Table) and block.caption:
        return plain(block.caption)
    if isinstance(block, Sidebar):
        return plain(block.title)
    return None


def number(sections: list[Section], prefix: str) -> None:
    """Give each section its dotted id: its position under its parent, from 1."""
    for position, section in enumerate(sections, start=1):
        section.id = f"{prefix}{position}"
        number(section.subsections, f"{section.id}.")


def set_pages(section: Section) -> None:
    """Widen a section's page range to its blocks and subsections."""
    pages = [section.source.page_start] + [page for block in section.blocks for page in block.pages]
    for child in section.subsections:
        set_pages(child)
        pages += [child.source.page_start, child.source.page_end]
    section.source.page_start, section.source.page_end = min(pages), max(pages)
