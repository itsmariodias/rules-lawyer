"""Sections and blocks to markdown. The only code that writes the book's markdown."""

from __future__ import annotations

import re
from dataclasses import replace

from rules_lawyer.srd.model import (
    Block,
    Contents,
    Field,
    Heading,
    ListBlock,
    Paragraph,
    Printed,
    Run,
    Section,
    Sidebar,
    StatBlock,
    Table,
    plain,
)

_SPECIAL = re.compile(r"([\\*_`])")
_BLOCK_MARK = re.compile(r"^([#>+-])")
_ORDERED_MARK = re.compile(r"^(\d+)\.")
# A stat block rendered on its own, outside the section tree: the deepest heading.
STAT_BLOCK_LEVEL = 6
ABILITY_HEADER = ["Ability", "Score", "MOD", "SAVE"]
# GFM tables cannot nest and trim leading spaces, so a row under a category
# row is marked instead of indented as printed.
CATEGORY_MEMBER = "\u21b3 "


def render(blocks: list[Block]) -> str:
    """Render blocks as markdown, one blank line between blocks.

    Args:
        blocks: Blocks in reading order.

    Returns:
        The markdown, ending in one newline.
    """
    return "\n\n".join(render_block(b) for b in blocks) + "\n"


def render_book(title: str, sections: list[Section],
                ) -> tuple[str, dict[str, tuple[int, int]], list[tuple[int, int, Printed]]]:
    """Render the book: its title, then each section's heading, blocks and subsections.

    The title is a level 1 heading, and the book's own headings keep their
    levels, so its chapters are level 1 beside it. A float's caption, title
    or name is its section's heading, so it is not rendered again. Pages
    stay in the JSON; the markdown reads straight through them.

    Args:
        title: The title every page's footer prints.
        sections: The book's top-level sections.

    Returns:
        The markdown, ending in one newline; each section's span of it by id,
        from its heading to the end of its last subsection; and each part
        rendered (a section's heading, a block) with its span, in order.
    """
    chunks: list[str] = []
    spans: dict[str, tuple[int, int]] = {}
    parts: list[tuple[int, int, Printed]] = []
    end = 0

    def add(chunk: str, part: Printed | None = None) -> int:
        nonlocal end
        start = end + 2 if chunks else 0    # chunks are joined by one blank line
        chunks.append(chunk)
        end = start + len(chunk)
        if part is not None:
            parts.append((start, end, part))
        return start

    def add_section(section: Section) -> None:
        start = add(f"{'#' * section.level} {section.heading}", section)
        for block in section.blocks:
            add(render_block(untitled(block)), block)
        for child in section.subsections:
            add_section(child)
        spans[section.id] = (start, end)

    add(f"# {title}")
    for section in sections:
        add_section(section)
    return "\n\n".join(chunks) + "\n", spans, parts


def section_text(section: Section) -> str:
    """A section's own text, without its heading or subsections, as the markdown renders it.

    Args:
        section: A section.

    Returns:
        Its blocks' markdown, a blank line between them.
    """
    return "\n\n".join(render_block(untitled(block)) for block in section.blocks)


def untitled(block: Block) -> Block:
    """A float without the caption, title or name its section's heading shows.

    Args:
        block: Any block.

    Returns:
        A copy without it for a float; any other block unchanged.
    """
    match block:
        case Table():
            return replace(block, caption=[])
        case Sidebar():
            return replace(block, title=[])
        case StatBlock():
            return replace(block, name="")
    return block


def render_block(block: Block) -> str:
    """One block as markdown.

    Args:
        block: Any block.

    Returns:
        Its markdown, without a trailing newline.
    """
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
    """A nested list, one item per entry, indented by level, page last.

    Args:
        block: A run of contents entries.

    Returns:
        The list's markdown.
    """
    top = min(e.level for e in block.entries)
    return "\n".join(f"{'  ' * (e.level - top)}- {render_runs(e.runs)} (p. {e.page})"
                     for e in block.entries)


def render_list(block: ListBlock) -> str:
    """One item per line; an item's later blocks indented beneath it.

    Args:
        block: A list.

    Returns:
        The list's markdown.
    """
    items = []
    for number, item in enumerate(block.items, start=block.start):
        marker = f"{number}." if block.ordered else "-"
        pad = " " * (len(marker) + 1)
        body = "\n\n".join(render_block(b) for b in item).replace("\n", "\n" + pad)
        items.append(f"{marker} {body}")
    return "\n".join(items)


def render_sidebar(block: Sidebar) -> str:
    """A blockquote: the title in bold, then the sidebar's blocks.

    Args:
        block: A sidebar.

    Returns:
        The blockquote's markdown.
    """
    parts = ([f"**{plain(block.title)}**"] if block.title else []) + [render_block(b) for b in block.blocks]
    return "\n".join("> " + line if line else ">" for line in "\n\n".join(parts).split("\n"))


def render_stat_block(block: StatBlock) -> str:
    """A stat block: its name as a heading (if it has one here), a line per field, the scores
    as a table after Speed, and each section under its bold title.

    Args:
        block: A stat block.

    Returns:
        Its markdown.
    """
    parts = [f"{'#' * STAT_BLOCK_LEVEL} {block.name}"] if block.name else []
    parts.append(render_runs(block.subtitle))
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
    """A field as its bold label and value.

    Args:
        field: A stat block field.

    Returns:
        One line of markdown.
    """
    return f"**{field.label}** {render_runs(field.value)}"


def render_table(block: Table) -> str:
    """A GFM table under its caption; header cells plain, since GFM bolds them.

    GFM has one header row, so a column's labels are joined top to bottom. A
    row under a category row starts with ``CATEGORY_MEMBER``.

    Args:
        block: A table.

    Returns:
        The caption, if any, a blank line, then the table.
    """
    width = max(len(row) for row in block.header + block.rows)
    header = [" ".join(label for row in block.header if (label := cell_text(row[i], plain_text=True)))
              for i in range(width)] if block.header else [""] * width
    lines = [row_text(header), row_text(["---"] * width)]
    for i, row in enumerate(block.rows):
        cells = [cell_text(c) for c in row]
        if block.under and block.under[i] is not None:
            cells[0] = CATEGORY_MEMBER + cells[0]
        lines.append(row_text(cells))
    table = "\n".join(lines)
    return f"{render_runs(block.caption)}\n\n{table}" if block.caption else table


def row_text(cells: list[str]) -> str:
    """One GFM table row.

    Args:
        cells: Each cell's markdown.

    Returns:
        The row, pipes around and between the cells.
    """
    return "| " + " | ".join(cells) + " |"


def cell_text(runs: list[Run], plain_text: bool = False) -> str:
    """A cell's markdown, with pipes escaped.

    Args:
        runs: The cell's runs.
        plain_text: Drop the runs' styles, as for a header cell.

    Returns:
        The cell's markdown.
    """
    text = _SPECIAL.sub(r"\\\1", plain(runs)) if plain_text else render_runs(runs)
    return text.replace("|", "\\|")


def render_runs(runs: list[Run]) -> str:
    """Runs as inline markdown.

    Args:
        runs: Runs in order.

    Returns:
        Their markdown, escaped and emphasised.
    """
    return "".join(render_run(r) for r in runs)


def escape_start(text: str) -> str:
    """Escape what markdown would read as a block marker at the start of a line.

    Args:
        text: A paragraph's markdown.

    Returns:
        The text, a leading "#", ">", "+", "-" or "1." escaped.
    """
    return _ORDERED_MARK.sub(r"\1\\.", _BLOCK_MARK.sub(r"\\\1", text))


def render_run(run: Run) -> str:
    """One run, escaped, with emphasis outside its edge whitespace.

    Args:
        run: A run.

    Returns:
        Its markdown.
    """
    text = _SPECIAL.sub(r"\\\1", run.text)
    core = text.strip()
    if not core or not (run.bold or run.italic):
        return text
    marked = f"_{core}_" if run.italic else core
    marked = f"**{marked}**" if run.bold else marked
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    return f"{lead}{marked}{trail}"
