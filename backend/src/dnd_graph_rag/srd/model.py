"""The block types: what the book is made of, independent of how it is read."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Run:
    """Text in one style."""

    text: str
    bold: bool = False
    italic: bool = False


@dataclass
class Heading:
    """A heading of the book."""

    level: int
    text: str
    page: int


@dataclass
class Paragraph:
    """One paragraph of the book, however many lines, columns or pages it spans."""

    runs: list[Run]
    pages: list[int]
    role: str | None = None   # "quote": every line indented from the column edge


@dataclass
class Entry:
    """One line of a table of contents: what, and on which page."""

    runs: list[Run]
    page: int
    # The heading level of what it points to: bold entries are chapters (1),
    # entries at the column edge are 2, indented entries 3.
    level: int


@dataclass
class Contents:
    """A run of contents entries, as printed under Contents or Index of Stat Blocks."""

    entries: list[Entry]
    pages: list[int]


@dataclass
class ListBlock:
    """A bulleted or numbered list; each item is its own blocks."""

    ordered: bool
    items: list[list[Block]]
    pages: list[int]
    start: int = 1            # the first item's number, for an ordered list


@dataclass
class Sidebar:
    """A framed box: a small-caps title over its own blocks."""

    title: list[Run]
    blocks: list[Block]
    pages: list[int]


@dataclass
class Table:
    """A table: optional caption, header rows, body rows of cells (each a run list)."""

    caption: list[Run]
    header: list[list[list[Run]]]
    rows: list[list[list[Run]]]
    pages: list[int]
    # Rows from each side-by-side half, while the table is read; not in the JSON.
    halves: list[int] = field(default_factory=list, compare=False, repr=False)


@dataclass
class Field:
    """One labelled field of a stat block: "AC" 17, "Senses" Darkvision 120 ft."""

    label: str
    value: list[Run]


@dataclass
class Section:
    """A stat block's Traits, Actions, Bonus Actions, Reactions or Legendary Actions."""

    title: str
    entries: list[Paragraph]


@dataclass
class StatBlock:
    """A creature's stat block, in the fixed form the book prints them.

    The fields run in printed order; the ability scores are printed after
    Speed. Each ability is [name, score, MOD, SAVE] as printed.
    """

    name: str
    subtitle: list[Run]
    fields: list[Field]
    abilities: list[list[str]]
    sections: list[Section]
    pages: list[int]


Block = Heading | Paragraph | Contents | ListBlock | Sidebar | Table | StatBlock


def add_page(pages: list[int], page: int) -> None:
    """Record that a block reaches ``page``, keeping the list ascending and unique."""
    if page not in pages:
        pages.append(page)
        pages.sort()


def plain(runs: list[Run]) -> str:
    """The text of runs, styles dropped."""
    return "".join(r.text for r in runs)
