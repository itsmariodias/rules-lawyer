"""Blocks to markdown. The only code that writes the book's markdown."""

from __future__ import annotations

import re

from .model import (Block, Contents, Field, Heading, ListBlock, Paragraph, Run, Sidebar,
                    StatBlock, Table)
from .text import plain

_SPECIAL = re.compile(r"([\\*_`])")
_BLOCK_MARK = re.compile(r"^([#>+-])")
_ORDERED_MARK = re.compile(r"^(\d+)\.")


def render(blocks: list[Block]) -> str:
    """Render blocks as markdown, one blank line between blocks.

    Args:
        blocks: Blocks in reading order.

    Returns:
        The markdown, ending in one newline.
    """
    return "\n\n".join(render_block(b) for b in blocks) + "\n"


def render_book(title: str, blocks: list[Block]) -> str:
    """Render the book: its title, then its blocks.

    The title is a level 1 heading, and the book's own headings keep their
    levels, so its chapters are level 1 beside it. Pages stay in the JSON;
    the markdown reads straight through them.

    Args:
        title: The title every page's footer prints.
        blocks: The book's blocks in reading order.

    Returns:
        The markdown, ending in one newline.
    """
    return f"# {title}\n\n{render(blocks)}"


def render_block(block: Block) -> str:
    """One block as markdown."""
    match block:
        case Heading():
            return f"{'#' * block.level} {block.text}"
        case Paragraph():
            text = escape_start(render_runs(block.runs))
            return f"> {text}" if block.role == "quote" else text
        case Contents():
            return render_contents(block)
        case ListBlock():
            return render_list(block)
        case Sidebar():
            return render_sidebar(block)
        case Table():
            return render_table(block)
        case StatBlock():
            return render_stat_block(block)


def render_contents(block: Contents) -> str:
    """A nested list, one item per entry, indented by level, page last."""
    top = min(e.level for e in block.entries)
    return "\n".join(f"{'  ' * (e.level - top)}- {render_runs(e.runs)} (p. {e.page})"
                     for e in block.entries)


def render_list(block: ListBlock) -> str:
    """One item per line; an item's later blocks indented beneath it."""
    items = []
    for number, item in enumerate(block.items, start=block.start):
        marker = f"{number}." if block.ordered else "-"
        pad = " " * (len(marker) + 1)
        body = "\n\n".join(render_block(b) for b in item).replace("\n", "\n" + pad)
        items.append(f"{marker} {body}")
    return "\n".join(items)


def render_sidebar(block: Sidebar) -> str:
    """A blockquote: the title in bold, then the sidebar's blocks."""
    parts = ([f"**{plain(block.title)}**"] if block.title else []) + [render_block(b) for b in block.blocks]
    return "\n".join("> " + line if line else ">" for line in "\n\n".join(parts).split("\n"))


# The deepest heading, so a creature printed inside a spell or item nests under it.
STAT_BLOCK_LEVEL = 6
ABILITY_HEADER = ["Ability", "Score", "MOD", "SAVE"]


def render_stat_block(block: StatBlock) -> str:
    """A stat block: its name as a heading, a line per field, the scores as a table after
    Speed, and each section under its bold title."""
    parts = [f"{'#' * STAT_BLOCK_LEVEL} {block.name}", render_runs(block.subtitle)]
    for field in block.fields:
        parts.append(render_field(field))
        if field.label == "Speed":
            parts.append("\n".join([row_text(ABILITY_HEADER), row_text(["---"] * 4)]
                                   + [row_text(row) for row in block.abilities]))
    for section in block.sections:
        parts.append(f"**{section.title}**")
        parts += [render_block(e) for e in section.entries]
    return "\n\n".join(parts)


def render_field(field: Field) -> str:
    """A field as its bold label and value."""
    return f"**{field.label}** {render_runs(field.value)}"


def render_table(block: Table) -> str:
    """A GFM table under its caption; header cells plain, since GFM bolds them.

    GFM has one header row, so a column's labels are joined top to bottom.
    """
    width = max(len(row) for row in block.header + block.rows)
    header = [" ".join(label for row in block.header if (label := cell_text(row[i], plain_text=True)))
              for i in range(width)] if block.header else [""] * width
    lines = [row_text(header), row_text(["---"] * width)]
    lines += [row_text([cell_text(c) for c in row]) for row in block.rows]
    table = "\n".join(lines)
    return f"{render_runs(block.caption)}\n\n{table}" if block.caption else table


def row_text(cells: list[str]) -> str:
    """One GFM table row."""
    return "| " + " | ".join(cells) + " |"


def cell_text(runs: list[Run], plain_text: bool = False) -> str:
    """A cell's markdown, with pipes escaped."""
    text = _SPECIAL.sub(r"\\\1", plain(runs)) if plain_text else render_runs(runs)
    return text.replace("|", "\\|")


def render_runs(runs: list[Run]) -> str:
    """Runs as inline markdown."""
    return "".join(render_run(r) for r in runs)


def escape_start(text: str) -> str:
    """Escape what markdown would read as a block marker at the start of a line."""
    return _ORDERED_MARK.sub(r"\1\\.", _BLOCK_MARK.sub(r"\\\1", text))


def render_run(run: Run) -> str:
    """One run, escaped, with emphasis outside its edge whitespace."""
    text = _SPECIAL.sub(r"\\\1", run.text)
    core = text.strip()
    if not core or not (run.bold or run.italic):
        return text
    marked = f"_{core}_" if run.italic else core
    marked = f"**{marked}**" if run.bold else marked
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    return f"{lead}{marked}{trail}"
