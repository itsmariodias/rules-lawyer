"""The block types: what the book is made of, independent of how it is read.

Pydantic dataclasses, so a block is built positionally like any dataclass,
validated when built or loaded, and written to JSON by ``BLOCKS``. Each block
names its ``type``, which tells the union apart when the JSON is read back.
"""

from __future__ import annotations

from dataclasses import field
from typing import Annotated, Literal

import pydantic
from pydantic import TypeAdapter, model_serializer, model_validator
from pydantic.dataclasses import dataclass, rebuild_dataclass


@dataclass
class Run:
    """Text in one style. In the JSON a plain run is its text, a styled run an object."""

    text: str
    bold: bool = False
    italic: bool = False

    @model_validator(mode="before")
    @classmethod
    def _from_text(cls, data: object) -> object:
        return {"text": data} if isinstance(data, str) else data

    @model_serializer(mode="wrap")
    def _to_text(self, handler: pydantic.SerializerFunctionWrapHandler) -> str | dict:
        if not (self.bold or self.italic):
            return self.text
        return {key: value for key, value in handler(self).items() if value}


@dataclass
class Heading:
    """A heading of the book."""

    type: Literal["heading"] = field(default="heading", kw_only=True, repr=False)
    level: int
    text: str
    page: int


@dataclass
class Paragraph:
    """One paragraph of the book, however many lines, columns or pages it spans."""

    type: Literal["paragraph"] = field(default="paragraph", kw_only=True, repr=False)
    runs: list[Run]
    pages: list[int]
    # "quote": every line indented from the column edge.
    role: Annotated[str | None, pydantic.Field(exclude_if=lambda role: role is None)] = None


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

    type: Literal["contents"] = field(default="contents", kw_only=True, repr=False)
    entries: list[Entry]
    pages: list[int]


@dataclass
class ListBlock:
    """A bulleted or numbered list; each item is its own blocks."""

    type: Literal["list"] = field(default="list", kw_only=True, repr=False)
    ordered: bool
    items: list[list[Block]]
    pages: list[int]
    # The first item's number, for an ordered list.
    start: Annotated[int, pydantic.Field(exclude_if=lambda start: start == 1)] = 1


@dataclass
class Sidebar:
    """A framed box: a small-caps title over its own blocks."""

    type: Literal["sidebar"] = field(default="sidebar", kw_only=True, repr=False)
    title: list[Run]
    blocks: list[Block]
    pages: list[int]


@dataclass
class Table:
    """A table: optional caption, header rows, body rows of cells (each a run list)."""

    type: Literal["table"] = field(default="table", kw_only=True, repr=False)
    caption: list[Run]
    header: list[list[list[Run]]]
    rows: list[list[list[Run]]]
    pages: list[int]
    # For each row, the index of the category row it is printed under, or None
    # ("Saddle" over Exotic, Military and Riding, not Sled, page 100); empty
    # when the table has no categories.
    under: Annotated[list[int | None], pydantic.Field(exclude_if=lambda under: not under)] = field(
        default_factory=list)
    # While the table is read, not in the JSON: rows from each side-by-side
    # half, and whether each row's first cell is indented from its label.
    halves: Annotated[list[int], pydantic.Field(exclude=True)] = field(
        default_factory=list, compare=False, repr=False)
    indented: Annotated[list[bool], pydantic.Field(exclude=True)] = field(
        default_factory=list, compare=False, repr=False)


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

    type: Literal["statblock"] = field(default="statblock", kw_only=True, repr=False)
    name: str
    subtitle: list[Run]
    fields: list[Field]
    abilities: list[list[str]]
    sections: list[Section]
    pages: list[int]


Block = Annotated[Heading | Paragraph | Contents | ListBlock | Sidebar | Table | StatBlock,
                  pydantic.Field(discriminator="type")]
for _container in (ListBlock, Sidebar):
    rebuild_dataclass(_container)
# Writes blocks to JSON-ready data (``dump_python``) and reads them back (``validate_python``).
BLOCKS = TypeAdapter(list[Block])


def add_page(pages: list[int], page: int) -> None:
    """Record that a block reaches ``page``, keeping the list ascending and unique."""
    if page not in pages:
        pages.append(page)
        pages.sort()


def plain(runs: list[Run]) -> str:
    """The text of runs, styles dropped."""
    return "".join(r.text for r in runs)
