"""PDF pages to visual lines: spans grouped by column and baseline, the footer split off."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from rules_lawyer.srd.model import Box

# Optional: only parsing opens the PDF, and the Docker image, which ships the
# parsed artifact, leaves it out. Annotations are strings, so they need none.
try:
    import pymupdf
except ModuleNotFoundError:
    pymupdf = None

# Measured over all 364 pages: the only text below this baseline is the
# footer, a page number and the book's title, "System Reference Document
# 5.2.1", at 755.
FOOTER_BASELINE = 740.0
# Spans within this distance share a line. Baselines, not bbox tops: tops are
# inflated by font metrics.
BASELINE_TOLERANCE = 3.0
# A line's box from its baseline and type size, in ems: PyMuPDF reports 95 of
# 107 lines on a typical page as 56pt tall, so its boxes are not used.
ASCENT = 0.80
DESCENT = 0.24
# A superscript sits up to this far above the baseline it belongs to.
SUPERSCRIPT_RISE = 5.0
# Spans of one line with no space between them are a word space apart when
# their gap is wider than this: within a word the gaps are under 0.5pt, word
# spaces 2.2pt or more (small-caps titles, "Playing on a Grid", page 13; the
# "Gray Ooze" stat block title, page 293, whose space is a span of its own).
WORD_GAP = 1.0
# A column's left edge is where at least this many lines start, with nothing
# but table text printed in the strip just left of it. Table cells also share
# left edges, but the page's prose crosses the strip beside them; a table may
# cross the gutter itself (page 9's Skills table runs the page's width).
MIN_COLUMN_LINES = 3
COLUMN_GUTTER = 2.0
# Starts nearer than this to a column's edge are indents within it. The
# narrowest columns (page 2's three) are 165pt apart; indents are under 15pt.
MIN_COLUMN_WIDTH = 100.0
# Lines starting this far right of an edge count towards it: a column may
# hold only a table inset from its edge (Trinkets, page 26: caption at 313.5,
# header at 317.5, 34 rows at 325).
INSET = 15.0
# A sidebar is a light grey box with a dark shadow box behind it, offset 4pt
# left and below (18 boxes on 17 pages). Table rows share the light grey but
# never have the shadow.
SIDEBAR_FILL = 0.903
SHADOW_FILL = 0.137
FILL_TOLERANCE = 0.02
# A table across both columns shades its rows in the sidebar grey from margin
# to margin (Starting Equipment at Higher Levels, page 24; the class tables;
# 19 pages). Its unshaded rows and header are within this of a shaded one:
# rows step 15.1pt, a wrapped cell's lines 12.5.
ROW_REACH = 16.0
# Page 5: table header labels are GillSans-SemiBold 9.2pt, cells GillSans 9.5pt.
HEADER_FONT = ("GillSans-SemiBold", 9.2)
CELL_FONT = ("GillSans", 9.5)
# Cells may hold italic (spell names in the spell lists; "an M engraved",
# Trinkets row 49, page 27): 819 lines.
TABLE_FONTS = (HEADER_FONT, CELL_FONT, ("GillSans-Italic", 9.5))
# Notes under a table are GillSans at 8pt or less (15 lines and their daggers).
TABLE_NOTE = 8.0
# Header labels may be semibold at the cell size ("Weight", "Cost", page 91):
# no evidence of a prose column, and part of a table across both. Bold at
# the cell size marks numbers and names inside cells ("on a **1**, a
# **Camel**", Hat of Many Spells, page 225).
TABLE_TYPE = (*TABLE_FONTS, (HEADER_FONT[0], CELL_FONT[1]), ("GillSans-Bold", CELL_FONT[1]))


@dataclass
class Span:
    """A run of text in one font, as PyMuPDF reports it."""

    text: str
    font: str
    size: float
    x0: float
    x1: float
    baseline: float = 0.0  # where on the page it is printed; spans of a line share it within 3pt
    shaded: bool = False  # printed on a shaded table row

    @property
    def face(self) -> tuple[str, float]:
        """The span's font and size, as the book's type is told apart."""
        return self.font, self.size


@dataclass
class Line:
    """One visual line: the spans sharing a baseline in one column, left to right."""

    page: int
    baseline: float
    spans: list[Span]
    column: int = 0
    left: float = 0.0       # the column's (or frame's) left edge; indents are measured from it
    right: float = 0.0      # the furthest any line of that column (or frame) reaches
    frame: int | None = None  # which sidebar frame on the page holds the line, if any

    @property
    def x1(self) -> float:
        """Right edge of the last span."""
        return self.spans[-1].x1

    @property
    def x0(self) -> float:
        """Left edge of the first span."""
        return self.spans[0].x0

    @property
    def size(self) -> float:
        """Largest type size on the line."""
        return max(s.size for s in self.spans)

    @property
    def text(self) -> str:
        """The line's text, unstyled, a space wherever a word gap separates spans."""
        return "".join((" " if before and word_gap(before, span) else "") + span.text
                       for before, span in zip([None, *self.spans], self.spans))


@dataclass
class Book:
    """The book's title and each page's lines, footers removed."""

    title: str
    pages: list[list[Line]]


def word_gap(before: Span, span: Span) -> bool:
    """Whether a word space separates two spans of a line that print none between them.

    Args:
        before: The span on the left.
        span: The span after it.

    Returns:
        True if the gap between them is wider than ``WORD_GAP``.
    """
    return span.x0 - before.x1 > WORD_GAP


def column_key(line: Line) -> tuple[int, int]:
    """Where a line is printed.

    Args:
        line: A line of the book.

    Returns:
        Its page and column.
    """
    return line.page, line.column


def boxes_of(lines: list[Line]) -> list[Box]:
    """Each line's box: its spans' extent, from its baseline up by ``ASCENT`` and down by ``DESCENT``.

    Args:
        lines: Lines of the book.

    Returns:
        One box per line, in PDF points rounded to 0.1.
    """
    return [Box(line.page, round(line.x0, 1), round(line.baseline - ASCENT * line.size, 1),
                round(line.x1, 1), round(line.baseline + DESCENT * line.size, 1)) for line in lines]


def pages_of(lines: list[Line]) -> list[int]:
    """The pages the lines are printed on.

    Args:
        lines: Lines of the book.

    Returns:
        The page numbers in order, each once.
    """
    return sorted({line.page for line in lines})


def read_pages(pdf_path: Path) -> Book:
    """Read every page of the PDF as lines in top-to-bottom order.

    Args:
        pdf_path: The SRD PDF.

    Returns:
        The title every footer prints, and one list of lines per page.

    Raises:
        ModuleNotFoundError: PyMuPDF is not installed.
        ValueError: The footers do not all print the same title.
    """
    if pymupdf is None:
        raise ModuleNotFoundError(
            "Parsing the PDF needs PyMuPDF, which is not installed: "
            "`uv sync` installs it with the default groups.")
    with pymupdf.open(pdf_path) as doc:
        split = [split_footer(page_lines(page, n)) for n, page in enumerate(doc, start=1)]
    titles = {title for _, title in split}
    if len(titles) != 1:
        raise ValueError(f"footers disagree on the title: {sorted(titles)}")
    return Book(titles.pop(), [body for body, _ in split])


def split_footer(lines: list[Line]) -> tuple[list[Line], str]:
    """Separate a page's footer from its body.

    Args:
        lines: One page from ``page_lines``.

    Returns:
        The body lines, and the footer's text without its page number.
    """
    body = [line for line in lines if line.baseline < FOOTER_BASELINE]
    footer = [s.text.strip() for line in lines if line.baseline >= FOOTER_BASELINE
              for s in line.spans if not s.text.strip().isdigit()]
    return body, " ".join(footer)


def page_lines(page: pymupdf.Page, number: int) -> list[Line]:
    """Group a page's spans into lines, column by column, top to bottom.

    Args:
        page: A PyMuPDF page.
        number: Its 1-based page number.

    Returns:
        The page's lines in reading order: the first column top to bottom,
        then the next. Each line's spans are left to right.
    """
    spans: list[Span] = []
    starts: Counter[float] = Counter()
    prose: Counter[float] = Counter()
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            kept = [Span(s["text"], s["font"], round(s["size"], 1), s["bbox"][0], s["bbox"][2],
                         s["origin"][1]) for s in line["spans"] if s["text"].strip()]
            spans += kept
            if kept and kept[0].baseline < FOOTER_BASELINE:
                # Whole points: lines of one column start up to 0.1pt apart.
                x = float(round(kept[0].x0))
                starts[x] += 1
                if kept[0].face not in TABLE_TYPE:
                    prose[x] += 1
    spans = attach_superscripts(spans)
    drawings = page.get_drawings()
    frames = sidebar_frames(drawings)
    shading = [d["rect"] for d in drawings if filled(d, SIDEBAR_FILL) and d["rect"] not in frames]
    edges = shaded_halves(column_edges(starts, prose, [span for span in spans
                                                       if span.baseline < FOOTER_BASELINE
                                                       and not is_table_or_note(span)]), shading)
    rows = row_shading(drawings, frames)
    for span in spans:
        span.shaded = any(r.contains(inside(span)) for r in rows)
    wide = spanning_cells(spans, shaded_across(shading, edges))
    placed = [(0 if id(span) in wide else column_of(span.x0, edges), span) for span in spans]

    lines: list[Line] = []
    for column, span in sorted(placed, key=lambda pair: (pair[0], pair[1].baseline)):
        frame = frame_of(span, frames)
        last = lines[-1] if lines else None
        if (last and (last.column, last.frame) == (column, frame)
                and span.baseline - last.baseline <= BASELINE_TOLERANCE):
            last.spans.append(span)
        else:
            lines.append(Line(number, span.baseline, [span], column, edges[column], frame=frame))
    for line in lines:
        line.spans.sort(key=lambda s: s.x0)
    set_edges(lines)
    return lines


def attach_superscripts(spans: list[Span]) -> list[Span]:
    """Spans with each superscript joined to the span it is raised after.

    A superscript is smaller, touches the span's end, and sits above its
    baseline: "Special" and a dagger 3.2pt up (Travel Terrain, page 192), too
    far for ``BASELINE_TOLERANCE``.

    Args:
        spans: A page's spans; the spans superscripts join are changed in place.

    Returns:
        The spans less the superscripts.
    """
    kept = []
    for span in spans:
        base = next((s for s in spans if abs(span.x0 - s.x1) < 0.6 and span.size < 0.8 * s.size
                     and 0 < s.baseline - span.baseline <= SUPERSCRIPT_RISE), None)
        if base:
            base.text += span.text
            base.x1 = span.x1
        else:
            kept.append(span)
    return kept


def is_table_or_note(span: Span) -> bool:
    """Whether a span is a table's: a header or cell, or a note under it.

    A note may run the page's width (GillSans 8pt and its daggers, Travel
    Terrain, page 192).

    Args:
        span: A span of the page.

    Returns:
        True for a table's span.
    """
    return span.face in TABLE_FONTS or (span.font.startswith("GillSans") and span.size <= TABLE_NOTE)


def set_edges(lines: list[Line]) -> None:
    """Give each line its column's right edge, and framed lines their frame's edges.

    The right edge is the column's text, not its tables: a table across both
    columns would put it at the far margin.

    Args:
        lines: A page's lines, given ``right`` (and ``left`` if framed) in place.
    """
    groups: dict[tuple[int, int | None], list[Line]] = {}
    for line in lines:
        if line.baseline < FOOTER_BASELINE:
            groups.setdefault((line.column, line.frame), []).append(line)
    for group in groups.values():
        text = [line for line in group if not all(s.face in TABLE_FONTS for s in line.spans)]
        right = max(line.x1 for line in text or group)
        left = min(line.x0 for line in group)
        for line in group:
            line.right = right
            if line.frame is not None:
                line.left = left


def filled(drawing: dict, shade: float) -> bool:
    """Whether a drawing is filled in the given grey.

    Args:
        drawing: A drawing from ``Page.get_drawings``.
        shade: The grey level, 0 black to 1 white.

    Returns:
        True if every colour component is within ``FILL_TOLERANCE`` of it.
    """
    fill = drawing.get("fill")
    return bool(fill) and all(abs(c - shade) < FILL_TOLERANCE for c in fill)


def sidebar_frames(drawings: list[dict]) -> list[pymupdf.Rect]:
    """The page's sidebar boxes: light grey fills with a dark shadow behind.

    Args:
        drawings: The page's drawings.

    Returns:
        The frames' rectangles.
    """
    shadows = [d["rect"] for d in drawings if filled(d, SHADOW_FILL)]
    return [d["rect"] for d in drawings if filled(d, SIDEBAR_FILL)
            and any(s.x0 < d["rect"].x0 and s.y1 > d["rect"].y1 and s.intersects(d["rect"])
                    for s in shadows)]


def row_shading(drawings: list[dict], frames: list[pymupdf.Rect]) -> list[pymupdf.Rect]:
    """The shaded table rows: sidebar-grey rectangles outside sidebar frames.

    Rows alternate, so every row boundary is a change of shading (page 27).

    Args:
        drawings: The page's drawings.
        frames: Its sidebar frames, from ``sidebar_frames``.

    Returns:
        One rectangle per shaded row.
    """
    return [pymupdf.Rect(item[1]) for d in drawings
            if filled(d, SIDEBAR_FILL) and d["rect"] not in frames
            for item in d["items"] if item[0] == "re"]


def shaded_across(shading: list[pymupdf.Rect], edges: list[float]) -> list[pymupdf.Rect]:
    """Table shading that crosses the gutter: from the first column into the second.

    Shading starting just left of the second edge is that column's own: the
    edge is measured from text inset in the shading (317 over 313.5, page 27).

    Args:
        shading: The page's table shading.
        edges: Its column edges.

    Returns:
        The shading crossing the gutter; empty on a one-column page.
    """
    if len(edges) < 2:
        return []
    return [r for r in shading if r.x0 < edges[1] - INSET and r.x1 > edges[1]]


def shaded_halves(edges: list[float], shading: list[pymupdf.Rect]) -> list[float]:
    """Add the second column of a page holding only a table printed in halves.

    With no prose, nothing starts often enough at the second column to
    measure it (Trinkets, page 27). But each half shades its own rows: a
    block from the first edge, and one beside it at the same height past a
    gap, whose left side is the second column's edge.

    Args:
        edges: The measured edges.
        shading: The page's table shading, one rectangle per table half.

    Returns:
        The edges, with the second added if only one was measured.
    """
    if len(edges) != 1:
        return edges
    for left in shading:
        for right in shading:
            if (abs(left.x0 - edges[0]) < INSET and left.x1 + COLUMN_GUTTER < right.x0
                    and right.x0 - edges[0] >= MIN_COLUMN_WIDTH
                    and min(left.y1, right.y1) > max(left.y0, right.y0)):
                return [edges[0], float(math.floor(right.x0))]
    return edges


def spanning_cells(spans: list[Span], shading: list[pymupdf.Rect]) -> set[int]:
    """The ids of table spans in a table across both columns.

    Each shaded band takes the table spans on its baselines, then grows a row
    at a time to the unshaded rows and header above and below it.

    Args:
        spans: The page's spans.
        shading: Shading across the gutter, from ``shaded_across``.

    Returns:
        The ``id`` of each span in such a table.
    """
    cells = [span for span in spans if span.face in TABLE_TYPE]
    wide: set[int] = set()
    for rect in shading:
        top, bottom = rect.y0, rect.y1
        grown = True
        while grown:
            grown = False
            for span in cells:
                if id(span) not in wide and top - ROW_REACH <= span.baseline <= bottom + ROW_REACH:
                    wide.add(id(span))
                    top, bottom = min(top, span.baseline), max(bottom, span.baseline)
                    grown = True
    return wide


def frame_of(span: Span, frames: list[pymupdf.Rect]) -> int | None:
    """The index of the frame a span is printed in.

    Args:
        span: A span of the page.
        frames: The page's sidebar frames.

    Returns:
        The frame's index, or None outside every frame.
    """
    return next((i for i, rect in enumerate(frames) if rect.contains(inside(span))), None)


def inside(span: Span) -> pymupdf.Point:
    """A point just inside the span's start, for testing which box it is printed in.

    Args:
        span: A span of the page.

    Returns:
        A point 1pt right of its start and 1pt above its baseline.
    """
    return pymupdf.Point(span.x0 + 1, span.baseline - 1)


def column_edges(starts: Counter[float], prose: Counter[float], spans: list[Span]) -> list[float]:
    """The left edges of a page's columns, left to right.

    An edge leads the starts within ``INSET`` of it: it is the leftmost with
    ``MIN_COLUMN_LINES`` prose lines (an edge, not the indents beside it,
    which can be more), else the leftmost with any prose (a caption over an
    inset table), else the leftmost. A stray table label (307, page 53)
    never leads prose. The edge counts every line starting from it to
    ``INSET`` right of it. Every edge after the first leads some prose: a
    column of table cells beside a table's first column has a clear strip
    too (School, page 33). A column holding only a table half is found by
    ``shaded_halves``.

    Args:
        starts: How many lines start at each x.
        prose: How many of them are not table lines.
        spans: The page's body spans other than tables', to test the strip
            left of an edge.

    Returns:
        At least one edge.
    """
    def leads(x: float) -> bool:
        near = [y for y in starts if abs(y - x) < INSET]
        pool = ([y for y in near if prose[y] >= MIN_COLUMN_LINES] or [y for y in near if prose[y]]
                or near)
        return x == min(pool)

    def lines_from(x: float) -> int:
        return sum(count for y, count in starts.items() if x <= y < x + INSET)

    edges: list[float] = []
    for x in sorted(x for x in starts if leads(x) and lines_from(x) >= MIN_COLUMN_LINES):
        if edges and x - edges[-1] < MIN_COLUMN_WIDTH:
            continue
        # A caption may stand out 0.6pt left of the text, a point left once
        # rounded ("Deck of Illusions" at 313, its text at 314, page 217).
        left = min(y for y in starts if x - 1 <= y <= x)
        if not edges or (any(prose[y] for y in starts if x <= y < x + INSET)
                         and not any(s.x0 < left - 0.5 and s.x1 > left - COLUMN_GUTTER
                                     for s in spans)):
            edges.append(left)
    return edges or [0.0]


def column_of(x0: float, edges: list[float]) -> int:
    """The column a span starting at ``x0`` belongs to: the last edge at or left of it.

    Args:
        x0: The span's left edge.
        edges: The page's column edges, left to right.

    Returns:
        The column's index; 0 if the span starts left of every edge.
    """
    return max((i for i, edge in enumerate(edges) if edge <= x0 + 0.5), default=0)
