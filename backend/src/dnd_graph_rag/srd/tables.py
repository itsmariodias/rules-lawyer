"""Table lines to a table: header, rows and cells placed by column."""

from __future__ import annotations

import re
from dataclasses import replace
from itertools import takewhile

from .model import Run, Table, add_page
from .pages import CELL_FONT, HEADER_FONT, TABLE_FONTS, TABLE_TYPE, Line, Span
from .text import plain, runs_of

# Cells start up to 0.4pt left of their header label (1,596 cells, "Strength"
# at 317.1 under "Ability" at 317.5, page 5); a dash centred under a digit
# 2.0 to 2.3pt left (459, page 26); centred numbers start to its right.
CELL_SLACK = 2.5
# A header line may mix in labels at the cell size ("Class" at 9.2pt beside
# "Hit Point Maximum" at 9.5, page 22; 15 such lines). Alone, semibold 9.5pt
# is a label in running text ("Ability:", page 93).
HEADER_SIZES = (HEADER_FONT[1], CELL_FONT[1])
# Rows step 15.1pt; a cell wrapped onto more lines steps 12.5 (356 times).
ROW_STEP = 14.0
# A labelled field's wrapped lines hang 8pt right of its label (page 94).
HANG = 4.0


def is_header_line(line: Line) -> bool:
    """Whether every span is header type, at least one at the header size."""
    return (all(s.font == HEADER_FONT[0] and s.size in HEADER_SIZES for s in line.spans)
            and any(s.size == HEADER_FONT[1] for s in line.spans))


def header_count(lines: list[Line]) -> int:
    """How many of a table's leading lines are its header.

    The header lines, or else a first line with header labels over a line
    with none: Travel Terrain prints four of its six labels in the cell font
    (page 192). In a key/value table every line has one ("Primary Ability",
    page 28).
    """
    count = len(list(takewhile(is_header_line, lines)))
    labelled = [any((s.font, s.size) == HEADER_FONT for s in l.spans) for l in lines[:2]]
    return 1 if not count and labelled == [True, False] else count


def is_table_line(line: Line) -> bool:
    """Whether every span is table type (header or cell), outside a sidebar.

    Semibold at the cell size counts only after the first span: a creature's
    name inside a cell ("A **Treant** sprouts", Bag of Beans, page 211), not the
    label leading a spell's or tool's line ("Casting Time:", "Ability:").
    """
    return line.frame is None and (is_header_line(line) or (
        (line.spans[0].font, line.spans[0].size) in TABLE_FONTS
        and all((s.font, s.size) in TABLE_TYPE for s in line.spans[1:])))


def wraps_field(lines: list[Line], index: int) -> bool:
    """Whether line ``index`` wraps a labelled field, not a table.

    A spell's or tool's field is a semibold label and plain text at the cell
    size ("**Components:** V, S, M (a diamond worth 1,000+ GP," page 125); its
    wrapped lines are plain, each within a row step of the one above.
    """
    while index > 0:
        prev, line = lines[index - 1], lines[index]
        # Atop the next column a wrap hangs indented ("cimer (25 GP, 10 lb.)",
        # page 94); within one it follows a row step or less below.
        if ((prev.page, prev.column) == (line.page, line.column)
                and line.baseline - prev.baseline >= ROW_STEP
                or (prev.page, prev.column) != (line.page, line.column)
                and line.x0 - line.left < HANG):
            return False
        first = prev.spans[0]
        if (first.font, first.size) == (HEADER_FONT[0], CELL_FONT[1]):
            return not is_table_line(prev)
        if not is_table_line(prev):
            return False
        index -= 1
    return False


def table_run(lines: list[Line], start: int) -> list[Line]:
    """The table lines from ``start`` in its page and column.

    A cell wrapped onto a line led by a bold word is table type too when it
    sits within a row step of the line above ("**2,** Acheron", Plane Shift
    in Amulet of the Planes, page 209); ``is_table_line`` alone cannot tell
    it from a spell's "Casting Time:".
    """
    first = lines[start]
    end = start
    while end < len(lines) and (lines[end].page, lines[end].column) == (first.page, first.column):
        line = lines[end]
        if not (is_table_line(line) or end > start and line.frame is None
                and lines[end].baseline - lines[end - 1].baseline < ROW_STEP
                and all((s.font, s.size) in TABLE_TYPE for s in line.spans)):
            break
        end += 1
    return lines[start:end]


def table_end(lines: list[Line]) -> int:
    """How many of ``lines`` form one table: its header lines, then body lines up to a
    header line a row step or more below the last, which starts another (Scrying's two
    tables, page 160). Nearer, it is a label wrapped within its row ("Saving Throw /
    Proficiencies", page 28)."""
    start = header_count(lines)
    return next((i for i in range(max(start, 1), len(lines)) if is_header_line(lines[i])
                 and lines[i].baseline - lines[i - 1].baseline >= ROW_STEP), len(lines))


def table(caption: list[Run], lines: list[Line], hyphenated: set[str]) -> Table:
    """Build a table from its lines, the leading header lines setting the columns.

    The header line with the most labels sets the columns. A label above it
    is centred over its column ("Proficiency" over "Bonus", page 28), or
    spans several ("Distance Traveled Per …" over Minute, Hour and Day, page
    12) and is kept in the first.
    A line less than a row step below the one before continues its row (a
    cell wrapped onto more lines). A table printed in side-by-side halves, its
    header labels repeated ("Score, Modifier, Score, Modifier" on page 6), is
    one table: the halves are stacked, left first, as the book is read.

    Args:
        caption: The caption's runs, or empty.
        lines: The table's lines in order, header first.
        hyphenated: Output of ``compounds``, for undoing hyphenation.

    Returns:
        The table.
    """
    header = lines[:header_count(lines)]
    body = lines[len(header):]
    labels = max(header, key=lambda l: len(l.spans)) if header else body[0]
    columns = labels.spans
    header_cells = [cells_of(l, columns) if l is labels else centred_cells(l, labels)
                    for l in header]
    width = repeat_width([plain(runs_of(c, hyphenated)) for c in cells_of(labels, columns)]) \
        if header else len(columns)
    body_cells = [cells_of(l, columns) for l in body]
    halves = [wrapped_rows([cells[start:start + width] for cells in body_cells])
              for start in range(0, len(columns), width)]
    return Table(caption,
                 [[runs_of(c, hyphenated) for c in cells[:width]] for cells in header_cells],
                 [[runs_of(c, hyphenated) for c in row] for half in halves for row in half],
                 sorted({l.page for l in lines}), [len(half) for half in halves])


def extend_table(table: Table, rest: Table) -> None:
    """Add the rest of a table, broken off by a column or page break, to it.

    A table printed in halves flows half by half (Food, Drink, and Lodging,
    pages 101-102), unless its rows are numbered: then each half goes on with
    its own rest, in number order (Experience Points by Challenge Rating
    prints 0-10 beside 14-27, then 11-13 beside 28-30, page 256).
    """
    rows = table.rows + rest.rows
    if len(table.halves) > 1 and len(table.halves) == len(rest.halves):
        interleaved, start, more = [], 0, 0
        for size, extra in zip(table.halves, rest.halves):
            interleaved += table.rows[start:start + size] + rest.rows[more:more + extra]
            start, more = start + size, more + extra
        numbers = [number(plain(row[0])) for row in interleaved]
        if None not in numbers and numbers == sorted(numbers):
            rows = interleaved
        table.halves = [a + b for a, b in zip(table.halves, rest.halves)]
    table.rows = rows
    for page in rest.pages:
        add_page(table.pages, page)


def number(text: str) -> float | None:
    """A row's number: "14", "1/8", or the start of a range ("0–4"); None if not one."""
    match = re.match(r"(\d+)(?:/(\d+))?(?:\u2013\d+)?$", text.strip())
    if not match:
        return None
    return int(match[1]) / int(match[2] or 1)


def repeat_width(labels: list[str]) -> int:
    """The width of the repeating unit of header labels; all of them if none repeats."""
    for width in range(1, len(labels)):
        if len(labels) % width == 0 and labels == labels[:width] * (len(labels) // width):
            return width
    return len(labels)


def wrapped_rows(lines: list[list[list[Line]]]) -> list[list[list[Line]]]:
    """Rows from per-line cells.

    A line continues the row above if it is nearer than a row step and on the
    same shading: rows alternate shaded and plain, and a table printed in
    halves sets both on one line grid, so a row may sit a wrapped line's step
    below the last (rows 35 and 36 of Trinkets, page 27).
    """
    rows: list[list[list[Line]]] = []
    last: Span | None = None
    baseline = 0.0
    for cells in lines:
        if not any(cells):
            continue
        first = next(cell[0] for cell in cells if cell)
        span = first.spans[0]
        if rows and first.baseline - baseline < ROW_STEP and span.shaded == last.shaded:
            for kept, more in zip(rows[-1], cells):
                kept.extend(more)
        else:
            rows.append(cells)
        last, baseline = span, first.baseline
    return rows


def centred_cells(line: Line, labels: Line) -> list[list[Line]]:
    """Split a header line into cells: a span over several labels goes to the first it
    overlaps, any other to the label nearest its centre.

    Overlap, not centres, finds the first: "Spell Slots per Spell Level" starts
    over "1" but right of its centre (page 31).
    """
    centres = [(s.x0 + s.x1) / 2 for s in labels.spans]
    cells: list[list[Line]] = [[] for _ in centres]
    for span in line.spans:
        covered = [i for i, c in enumerate(centres) if span.x0 <= c <= span.x1]
        middle = (span.x0 + span.x1) / 2
        index = next(i for i, s in enumerate(labels.spans) if s.x1 > span.x0) \
            if len(covered) > 1 else \
            min(range(len(centres)), key=lambda i: abs(centres[i] - middle))
        if cells[index]:
            cells[index][0].spans.append(span)
        else:
            cells[index].append(replace(line, spans=[span]))
    return cells


def cells_of(line: Line, columns: list[Span]) -> list[list[Line]]:
    """Split a line into one single-line ``Line`` per column (empty where nothing is printed).

    A span goes under the one label it overlaps: right-aligned cells start left
    of their label ("25 GP" at 525.2 under "Cost" at 529.1, page 91). Over
    none or several, it goes to the last label starting left of it.
    """
    cells: list[list[Line]] = [[] for _ in columns]
    for span in line.spans:
        over = [i for i, label in enumerate(columns) if span.x0 < label.x1 and span.x1 > label.x0]
        index = over[0] if len(over) == 1 else \
            max((i for i, label in enumerate(columns) if label.x0 <= span.x0 + CELL_SLACK), default=0)
        if cells[index]:
            cells[index][0].spans.append(span)
        else:
            cells[index].append(Line(line.page, line.baseline, [span], line.column, line.left,
                                     line.right, line.frame))
    return cells
