"""
Layout-aware text extraction for the SRD PDF.

The SRD is laid out in columns, and a naive extraction reads across them.
PyMuPDF's own reading order (and pymupdf4llm's) merges paragraphs into
blocks and sometimes sorts a bottom-of-column fragment after the whole
facing column, which detaches a creature's ``AC / Initiative / HP / Speed``
line from its stat block and silently attributes it to a neighbour.

This module works at the *line* level instead:

  1. every text line is extracted with its bounding box and span styles
  2. running headers and footers are dropped
  3. the page's column frames are measured from the empty vertical strips
     between them, then checked against the grid the book as a whole uses
  4. tables are lifted out as units and their cells rebuilt from the exact
     x positions of the text, since most SRD rows have no ruling lines
  5. lines that span more than one frame split the page into *bands*, and
     within a band each column is read top to bottom in turn
  6. lines sharing a baseline are merged left to right, which is what
     reassembles a stat block's ability grid

Typography carries the structure: heading level comes from font size, stat
block titles and section headers have their own sizes, and small-caps
sidebar headings are recased.

The result is a list of ``Line`` records in true reading order.
``lines_to_markdown`` renders them as markdown, reports where each stat
block title landed so a creature can be tied back to its section, and keeps
each part's page rectangles so a character range can be drawn on the PDF.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import pymupdf


# ---------------------------------------------------------------------------
# Typography map (measured from the SRD's embedded fonts)
# ---------------------------------------------------------------------------
# GillSans-SemiBold is used for every document heading; the size determines
# the level.  11.0 is the page number in the footer, not a heading.
HEADING_SIZES: dict[float, int] = {
    26.0: 1,   # section title      e.g. "Monsters"
    18.0: 2,   # major heading      e.g. "Ghast", "Aboleth"
    14.8: 3,   # stat block name    e.g. "Ghast" (the card title)
    14.0: 3,   # regular heading
    12.0: 4,
    10.5: 5,
}

# The title printed on a stat block card.  It shares a heading level with the
# ordinary 14pt heading but is set one notch larger, which is what identifies
# a creature's stat block anywhere in the book.
STATBLOCK_NAME_SIZE = 14.8
STATBLOCK_NAME_LEVEL = 5

# Stat block section headers ("Traits", "Actions", ...) are plain GillSans 12,
# NOT GillSans-SemiBold — that distinction separates them from real headings.
STATBLOCK_SECTION_SIZE = 12.0
STATBLOCK_SECTIONS = {
    "traits", "actions", "bonus actions", "reactions",
    "legendary actions", "utility spells", "at will", "1/day each",
}

FOOTER_Y = 735.0          # anything below this is the running footer
GUTTER_TOLERANCE = 6.0    # slack when deciding if a line crosses the gutter
FRAME_GAP = 30.0          # min x distance between two distinct frames
GUTTER_WIDTH = 8.0        # min width (pt) of the empty strip between columns
COLUMN_TABLE_HEIGHT = 200.0  # min height (pt) for a table to count as a column
FRAME_SNAP = 15.0         # how far a page's frame may sit from the book's grid
BASELINE_TOLERANCE = 3.0  # max |Δy| for two lines to share a baseline
PARAGRAPH_SLACK = 3.0     # extra leading (pt) that marks a paragraph break

_FOOTER_RE = re.compile(r"^\s*\d*\s*System Reference Document", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@dataclass
class Line:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    baseline: float                 # text baseline; bbox tops are unreliable
    column: int                     # 0 = left, 1 = right, -1 = full width
    text: str                       # plain text, styles stripped
    markup: str                     # text with **bold** / _italic_ markers
    max_size: float
    fonts: set[str] = field(default_factory=set)
    heading_level: int | None = None
    is_statblock_section: bool = False
    is_statblock_name: bool = False
    is_small_caps: bool = False
    starts_paragraph: bool = False
    # Fragments that shared this baseline, left to right, with their left
    # edges — the raw material for rebuilding tables.
    cells: list[str] = field(default_factory=list)
    cell_x: list[float] = field(default_factory=list)
    table_id: int | None = None
    # Set on a table anchor line: the table's rows, already split into cells.
    rows: list[Line] = field(default_factory=list)

    @property
    def is_heading(self) -> bool:
        return self.heading_level is not None


# ---------------------------------------------------------------------------
# Small caps
# ---------------------------------------------------------------------------

def _titlecase(text: str) -> str:
    """
    Repair a small-caps heading.

    The SRD renders sidebar headings in a small-caps font whose subset
    encoding extracts as mixed case ("rEstinG", "playinG on a Grid").  The
    letters are right, only the casing is meaningless, so recase the words.
    """
    minor = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of",
             "on", "or", "the", "to", "up", "with"}
    words = text.lower().split()
    out = []
    for i, w in enumerate(words):
        if i > 0 and w in minor:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


# ---------------------------------------------------------------------------
# Span → markup
# ---------------------------------------------------------------------------

def _is_small_caps_heading(text: str, spans: list[dict]) -> bool:
    """
    Tell a small-caps sidebar heading from a stat block's ability grid.

    Both use an -SC700 subset, but the ability grid ("Str 14 +2 +2 …") is
    mostly plain-font digits while a sidebar heading is entirely bold words.
    """
    stripped = text.strip()
    if not stripped or any(ch.isdigit() for ch in stripped):
        return False
    if stripped.count(" ") > 8:
        return False
    return all(
        "Bold" in s["font"] or "SemiBold" in s["font"]
        for s in spans if s["text"].strip()
    )


def _span_markup(text: str, font: str) -> str:
    """Wrap a span in markdown emphasis according to its font."""
    if not text.strip():
        return text
    bold = "Bold" in font or "SemiBold" in font
    italic = "Italic" in font or "Oblique" in font
    lead = len(text) - len(text.lstrip())
    trail = len(text) - len(text.rstrip())
    core = text.strip()
    if bold and italic:
        core = f"**_{core}_**"
    elif bold:
        core = f"**{core}**"
    elif italic:
        core = f"_{core}_"
    return " " * lead + core + " " * trail


def _merge_markup(markup: str) -> str:
    """Collapse adjacent emphasis runs produced span-by-span."""
    markup = re.sub(r"\*\*(\s*)\*\*", r"\1", markup)
    markup = re.sub(r"_(\s*)_(?!_)", r"\1", markup)
    return markup


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _page_frames(page: pymupdf.Page, rects: list[pymupdf.Rect]) -> list[float]:
    """
    Infer the left edge of each text frame on a page.

    A column boundary is a strip of the page that no line of text crosses, so
    frames are found by projecting every line onto the x axis and looking for
    empty runs.  That is far steadier than clustering line start positions,
    which cannot tell a real column from a table's second cell.

    Lines inside a table are left out of the projection — a table's internal
    gutters are not page columns — and a table tall enough to fill a column
    on its own then contributes its left edge, since it leaves no loose lines
    to mark that column with.
    """
    width = int(page.rect.width) + 1
    coverage = [0] * width

    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for pl in block["lines"]:
            if not "".join(s["text"] for s in pl["spans"]).strip():
                continue
            x0, _, x1, _ = pl["bbox"]
            baseline = statistics.median([s["origin"][1] for s in pl["spans"]])
            if baseline >= FOOTER_Y:
                continue
            if any(r.x0 - TABLE_PADDING <= (x0 + x1) / 2 <= r.x1 + TABLE_PADDING
                   and r.y0 - TABLE_PADDING <= baseline <= r.y1 + TABLE_PADDING
                   for r in rects):
                continue
            for x in range(max(0, int(x0)), min(width, int(x1) + 1)):
                coverage[x] += 1

    occupied = [x for x in range(width) if coverage[x]]
    frames: list[float] = []
    if occupied:
        frames.append(float(occupied[0]))
        gutter_start: int | None = None
        for x in range(occupied[0], width):
            if coverage[x] == 0:
                if gutter_start is None:
                    gutter_start = x
            else:
                if gutter_start is not None and x - gutter_start >= GUTTER_WIDTH:
                    frames.append(float(x))
                gutter_start = None

    for rect in rects:
        if rect.height >= COLUMN_TABLE_HEIGHT and all(
            abs(rect.x0 - f) > FRAME_GAP for f in frames
        ):
            frames.append(rect.x0)

    return sorted(frames) or [float(page.rect.x0)]


def document_grid(frames_per_page: list[list[float]]) -> list[float]:
    """
    The column grid the book is laid out on, as the most common frame set.

    Individual pages can still be misread — a table the finder missed leaves
    its cell columns looking like page columns — so the grid found across the
    whole document is used to sanity-check each page in ``snap_to_grid``.
    """
    counts = Counter(tuple(round(f) for f in frames) for frames in frames_per_page)
    return [float(f) for f in counts.most_common(1)[0][0]]


def snap_to_grid(frames: list[float], grid: list[float]) -> list[float]:
    """
    Discard frames that the book's grid does not know about.

    A page that lines up with at least two grid columns is an ordinary page
    of the book, and any extra frame on it is an artefact of a table; a page
    that lines up with fewer is genuinely laid out differently (the contents
    run three and four columns) and keeps what it measured.
    """
    matched = [f for f in frames if any(abs(f - g) <= FRAME_SNAP for g in grid)]
    if len(matched) == len(frames):
        # Every frame is a grid column, so the page is an ordinary one and any
        # column the measurement missed is a column all the same: a table laid
        # across the gutter hides it by leaving no empty strip behind.
        return grid
    return matched if len(matched) >= 2 else frames


def _column_of(x0: float, x1: float, frames: list[float]) -> int:
    """
    Assign a line to a frame, or -1 when it spans more than one.

    A line that starts in one frame and reaches into the next is full width
    (a section title, or a table laid across the page) and acts as a band
    boundary rather than as column content.

    A frame's measured position is the leftmost thing that happens to sit in
    it, so content can begin a few points to its left; the same slack used
    to match a page against the book's grid applies here, or a table would
    read as spilling out of the column it fills.
    """
    idx = 0
    for i, fx in enumerate(frames):
        if x0 >= fx - FRAME_SNAP:
            idx = i
    if idx + 1 < len(frames) and x1 > frames[idx + 1] + GUTTER_TOLERANCE:
        return -1
    return idx


def _raw_lines(page: pymupdf.Page, page_no: int, frames: list[float]) -> list[Line]:
    out: list[Line] = []

    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for pl in block["lines"]:
            spans = pl["spans"]
            text = "".join(s["text"] for s in spans)
            if not text.strip():
                continue

            x0, y0, x1, y1 = pl["bbox"]
            if y0 >= FOOTER_Y or _FOOTER_RE.match(text):
                continue

            fonts = {s["font"] for s in spans}
            max_size = max(round(s["size"], 1) for s in spans)
            markup = _merge_markup("".join(_span_markup(s["text"], s["font"]) for s in spans))

            # small caps: the subset name carries an -SC suffix
            small_caps = any("SC" in f.rsplit("-", 1)[-1] for f in fonts)

            # heading?
            level = None
            statblock_section = False
            semibold = any("SemiBold" in f or f.endswith("-Bold") for f in fonts)
            if semibold and max_size in HEADING_SIZES:
                level = HEADING_SIZES[max_size]
            elif small_caps and _is_small_caps_heading(text, spans):
                # small-caps sidebar heading (rendered ~7pt but semantically H5)
                level = 5
            elif (max_size == STATBLOCK_SECTION_SIZE
                  and not semibold
                  and text.strip().lower().rstrip(".") in STATBLOCK_SECTIONS):
                statblock_section = True

            if level is not None or statblock_section:
                clean = re.sub(r"\s+", " ", text).strip()
                if small_caps:
                    clean = _titlecase(clean)
                text, markup = clean, clean

            column = _column_of(x0, x1, frames)

            out.append(Line(
                page=page_no, x0=x0, y0=y0, x1=x1, y1=y1,
                baseline=statistics.median([s["origin"][1] for s in spans]),
                column=column,
                text=text, markup=markup, max_size=max_size, fonts=fonts,
                heading_level=level, is_statblock_section=statblock_section,
                is_statblock_name=(level is not None and max_size == STATBLOCK_NAME_SIZE),
                is_small_caps=small_caps,
            ))
    return out


def _merge_baselines(lines: list[Line]) -> list[Line]:
    """
    Merge lines that share a baseline into one logical line, left to right.

    Stat block ability grids and the ``AC … Initiative …`` line are laid out
    as several independent text runs on the same baseline; without this they
    arrive as separate lines and the values lose their association.
    """
    if not lines:
        return []
    merged: list[Line] = []
    bucket: list[Line] = [lines[0]]
    for ln in lines[1:]:
        head = bucket[0]
        same_baseline = abs(ln.baseline - head.baseline) <= BASELINE_TOLERANCE
        # A heading never absorbs the body text it sits next to: their bounding
        # boxes overlap because of font metrics, but they are different things.
        same_kind = (
            ln.heading_level == head.heading_level
            and ln.is_statblock_section == head.is_statblock_section
            and ln.max_size == head.max_size
        )
        if same_baseline and same_kind:
            bucket.append(ln)
        else:
            merged.append(_join(bucket))
            bucket = [ln]
    merged.append(_join(bucket))
    return merged


def _join(bucket: list[Line]) -> Line:
    if len(bucket) == 1:
        bucket[0].cells = [bucket[0].markup.strip()]
        bucket[0].cell_x = [bucket[0].x0]
        return bucket[0]
    bucket = sorted(bucket, key=lambda l: l.x0)
    head = bucket[0]
    return Line(
        page=head.page,
        x0=min(l.x0 for l in bucket), y0=min(l.y0 for l in bucket),
        x1=max(l.x1 for l in bucket), y1=max(l.y1 for l in bucket),
        baseline=head.baseline,
        column=head.column,
        text=" ".join(l.text.strip() for l in bucket if l.text.strip()),
        markup=" ".join(l.markup.strip() for l in bucket if l.markup.strip()),
        max_size=max(l.max_size for l in bucket),
        fonts=set().union(*(l.fonts for l in bucket)),
        heading_level=head.heading_level,
        is_statblock_section=head.is_statblock_section,
        is_statblock_name=head.is_statblock_name,
        is_small_caps=head.is_small_caps,
        cells=[l.markup.strip() for l in bucket if l.markup.strip()],
        cell_x=[l.x0 for l in bucket if l.markup.strip()],
    )


def _mark_paragraphs(run: list[Line]) -> None:
    """
    Flag the lines in one column run that begin a new paragraph.

    The SRD sets body text on a fixed baseline grid, so the *modal* baseline
    step in a run is its leading; anything meaningfully larger is a paragraph
    break.  Deriving the leading per run rather than hard-coding it keeps the
    rule working across the sizes the book uses (9, 9.5 and 10 pt).
    """
    body = [l for l in run if not (l.is_heading or l.is_statblock_section)]
    if len(body) < 2:
        return
    deltas = [round(b.baseline - a.baseline, 1)
              for a, b in pairwise(body) if 0 < b.baseline - a.baseline < 40]
    if not deltas:
        return
    leading = Counter(deltas).most_common(1)[0][0]
    for a, b in pairwise(body):
        if b.baseline - a.baseline > leading + PARAGRAPH_SLACK or b.markup.startswith("\t"):
            b.starts_paragraph = True


TABLE_PADDING = 6.0       # slack when testing whether a line is inside a table
COLUMN_TOLERANCE = 15.0   # max x gap (pt) within one table column


def _table_rects(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """
    Locate table *regions* on a page.

    PyMuPDF's table finder is good at spotting where a table is but poor at
    splitting SRD rows into cells, because most rows have no ruling lines.
    So the region is all we take from it — the cells are rebuilt from the
    exact x positions of the text fragments, which the SRD aligns precisely.
    """
    try:
        return [pymupdf.Rect(t.bbox) for t in page.find_tables().tables]
    except (ValueError, RuntimeError):
        # The table finder gives up on a few pages; flowing text is the
        # correct fallback there, so a failure is not worth propagating.
        return []


def _rect_of(line: Line, rects: list[pymupdf.Rect]) -> int | None:
    cx, cy = (line.x0 + line.x1) / 2, line.baseline
    for i, r in enumerate(rects):
        if r.x0 - TABLE_PADDING <= cx <= r.x1 + TABLE_PADDING and \
           r.y0 - TABLE_PADDING <= cy <= r.y1 + TABLE_PADDING:
            return i
    return None


def _build_table(rows: list[Line], table_id: int, rect: pymupdf.Rect,
                 frames: list[float]) -> Line:
    """
    Turn the lines inside a table region into one anchor Line carrying its rows.

    Rows are baseline groups; cells are the fragments on that baseline in
    left-to-right order.  The anchor is what participates in page ordering,
    so a table always stays intact and in place.
    """
    grouped = _merge_baselines(sorted(rows, key=lambda l: (l.baseline, l.x0)))
    for g in grouped:
        g.table_id = table_id
    head = grouped[0]
    return Line(
        page=head.page, x0=rect.x0, y0=rect.y0, x1=rect.x1, y1=rect.y1,
        baseline=head.baseline,
        column=_column_of(rect.x0, rect.x1, frames),
        text="", markup="", max_size=head.max_size, fonts=set(),
        table_id=table_id, rows=grouped,
    )


def _join_split_headings(lines: list[Line]) -> list[Line]:
    """
    Rejoin a heading that the PDF set over two lines.

    "Curses and Magical Contagions" and "Index of Stat Blocks" are both set
    over two lines; left alone they become the sections "Curses and" and
    "Index of Stat", which are neither real headings nor usable graph
    entities.  Two heading lines belong together when they are the same
    level, overlap horizontally, and sit one line apart — which is checked
    across the whole page, because a heading can be split while the column
    it sits in is being read in a different order around it.
    """
    by_column: dict[int, list[Line]] = {}
    for line in lines:
        if line.is_heading:
            by_column.setdefault(line.column, []).append(line)

    absorbed: set[int] = set()
    pairs = [
        (a, b)
        for heads in by_column.values()
        for a, b in pairwise(sorted(heads, key=lambda l: l.baseline))
    ]
    for first, second in pairs:
        if id(first) in absorbed:
            continue
        overlaps = min(first.x1, second.x1) - max(first.x0, second.x0) > 0
        if (second.heading_level == first.heading_level
                and second.max_size == first.max_size
                and overlaps
                and 0 < second.baseline - first.baseline <= second.max_size * 1.6):
            first.text = f"{first.text} {second.text}".strip()
            first.markup = first.text
            first.x0, first.x1 = min(first.x0, second.x0), max(first.x1, second.x1)
            first.y1 = max(first.y1, second.y1)
            absorbed.add(id(second))

    return [l for l in lines if id(l) not in absorbed]


CAPTION_GAP = 30.0        # max distance (pt) from a caption to its table
TABLE_ROW_REACH = 20.0    # how far outside a rect a stray row may sit


def _absorb_edge_rows(rows: list[Line], rect: pymupdf.Rect, free: list[Line]) -> list[Line]:
    """
    Reclaim a row that sits just outside its table's detected rectangle.

    PyMuPDF bounds a table by the shaded rows it can see, so an unshaded
    first or last row falls outside — which is why the Bard cantrip list lost
    "Vicious Mockery" and the Apparatus of the Crab lost lever 10.  Such a row
    is recognised by geometry, not guessed: it must sit within a line or two
    of the rect and place at least two fragments under the table's own column
    positions.  Ordinary prose is a single fragment and never qualifies.

    Absorbed lines are removed from *free* and returned.
    """
    columns = {round(l.x0) for l in rows}

    by_baseline: dict[float, list[Line]] = {}
    for line in free:
        if line.is_heading or line.rows:
            continue
        if not (0 < line.baseline - rect.y1 <= TABLE_ROW_REACH
                or 0 < rect.y0 - line.baseline <= TABLE_ROW_REACH):
            continue
        if line.x0 < rect.x0 - COLUMN_TOLERANCE or line.x1 > rect.x1 + COLUMN_TOLERANCE:
            continue
        by_baseline.setdefault(round(line.baseline, 1), []).append(line)

    absorbed: list[Line] = []
    for group in by_baseline.values():
        aligned = {
            next(c for c in columns if abs(l.x0 - c) <= COLUMN_TOLERANCE)
            for l in group
            if any(abs(l.x0 - c) <= COLUMN_TOLERANCE for c in columns)
        }
        if len(group) >= 2 and len(aligned) >= 2:
            absorbed.extend(group)

    for line in absorbed:
        free.remove(line)
    return absorbed


def _promote_table_captions(anchors: list[Line], free: list[Line]) -> None:
    """
    Keep a full-width table's caption heading with the table.

    The SRD names a table in a heading directly above it.  When the table
    runs the width of the page but its caption sits at the foot of a column
    — "Apparatus of the Crab Levers" on p210 — reading order puts the entire
    facing column between the two, which is correct for the prose and wrong
    for the table: the caption belongs to it and nothing else.

    Making the caption full width too pins it immediately before its table,
    which is where a reader sees it.  Only the heading directly above the
    table qualifies, and only when nothing else in its column sits between.
    """
    for anchor in anchors:
        if anchor.column != -1:
            continue
        candidates = [
            l for l in free
            if l.is_heading and l.column != -1
            and 0 < anchor.y0 - l.baseline <= CAPTION_GAP
        ]
        if not candidates:
            continue
        caption = max(candidates, key=lambda l: l.baseline)
        intervening = any(
            l.column == caption.column and caption.baseline < l.baseline < anchor.y0
            for l in free if l is not caption
        )
        if intervening:
            continue
        caption.column = -1
        # Just ahead of the table, so the two stay adjacent once banded.
        caption.baseline = anchor.baseline - 0.1


def _order_page(lines: list[Line], rects: list[pymupdf.Rect],
                frames: list[float], next_table_id: int) -> tuple[list[Line], int]:
    """
    Order one page: pull tables out as atomic units, band the rest on
    full-width lines, then read the left column before the right.
    """
    if not lines:
        return [], next_table_id

    lines = _join_split_headings(lines)

    # 1. Tables become single anchor lines carrying their rows.
    in_table: dict[int, list[Line]] = {}
    free: list[Line] = []
    for ln in lines:
        idx = _rect_of(ln, rects)
        if idx is None or ln.is_heading:
            free.append(ln)
        else:
            in_table.setdefault(idx, []).append(ln)

    anchors: list[Line] = []
    for idx, rows in in_table.items():
        if len(rows) < 2:
            free.extend(rows)
            continue
        rows += _absorb_edge_rows(rows, rects[idx], free)
        anchors.append(_build_table(rows, next_table_id, rects[idx], frames))
        next_table_id += 1

    _promote_table_captions(anchors, free)

    # 2. Band on everything that spans the gutter.
    items = free + anchors
    full = sorted((l for l in items if l.column == -1), key=lambda l: l.baseline)
    columned = [l for l in items if l.column != -1]

    boundaries = [l.baseline for l in full]
    ordered: list[Line] = []
    prev = float("-inf")

    for i, fl in enumerate(full + [None]):
        upper = boundaries[i] if i < len(boundaries) else float("inf")
        band = [l for l in columned if prev <= l.baseline < upper]
        for col in range(len(frames)):
            side = sorted((l for l in band if l.column == col),
                          key=lambda l: (l.baseline, l.x0))
            tables = [l for l in side if l.rows]
            body = _merge_baselines([l for l in side if not l.rows])
            _mark_paragraphs(body)
            ordered.extend(sorted(body + tables, key=lambda l: (l.baseline, l.x0)))
        if fl is not None:
            if not fl.rows:
                fl.cells = fl.cells or [fl.markup.strip()]
                fl.cell_x = fl.cell_x or [fl.x0]
            ordered.append(fl)
            prev = fl.baseline

    return ordered, next_table_id


def extract_lines(pdf_path: Path) -> list[Line]:
    """Extract every text line of the PDF in true reading order."""
    doc = pymupdf.open(str(pdf_path))

    rects_per_page = [_table_rects(doc[pno]) for pno in range(doc.page_count)]
    frames_per_page = [_page_frames(doc[pno], rects_per_page[pno])
                       for pno in range(doc.page_count)]
    grid = document_grid(frames_per_page)

    out: list[Line] = []
    table_id = 0
    for pno in range(doc.page_count):
        page, rects = doc[pno], rects_per_page[pno]
        frames = snap_to_grid(frames_per_page[pno], grid)
        ordered, table_id = _order_page(
            _raw_lines(page, pno + 1, frames), rects, frames, table_id
        )
        out.extend(ordered)
    doc.close()
    return out


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

# A word broken across a line break: the hyphen may sit inside an emphasis
# run, so allow trailing ``*``/``_`` markers after it.
_HYPHEN_BREAK_RE = re.compile(r"(\w)[­-]([*_]*)$")

def lines_to_markdown(
    lines: list[Line],
) -> tuple[str, dict[int, int], list[dict]]:
    """
    Render ordered lines as markdown with ``<!-- PAGE:n -->`` markers.

    Consecutive body lines are joined into paragraphs, undoing the PDF's
    hard line wrapping (including hyphenation across line breaks).  A new
    paragraph starts on a heading, a column or page change, an unusually
    large vertical gap, or an indented first line.

    Returns three things: the markdown; for each stat block title, its
    character offset within it — the anchor that ties a creature record to
    the section of the book it was printed in; and an *anchor* per emitted
    part, recording the character range it occupies alongside the page and
    bounding box of every line that produced it.

    Anchors are per part, not per character: reflowing a paragraph destroys
    any character-level correspondence with the page.  Part-level is enough,
    because a section begins and ends on a part boundary, so its character
    range maps to whole parts and those to rectangles on the PDF.

    Stat block titles are emitted at the deepest heading level rather than
    the level their type size implies.  Honouring the size would let a
    creature summoned by a spell outrank the spell descriptions around it and
    swallow them; at the deepest level a card always nests inside whatever it
    was printed in.
    """
    parts: list[str] = []
    offsets: dict[int, int] = {}
    anchors: list[dict] = []
    para: list[str] = []
    # The lines behind the paragraph being accumulated, so a flushed
    # paragraph knows which boxes on the page it came from.
    para_lines: list[Line] = []
    page = None
    prev: Line | None = None
    # Parts are joined with a blank line, so each contributes its own length
    # plus the two newlines that follow it.  Tracking the running total lets
    # a stat block title record where it will land in the finished markdown.
    written = 0

    def emit(part: str, sources: list[Line] = []) -> None:
        nonlocal written
        if part.strip():
            parts.append(part)
            if sources:
                anchors.append({
                    "start": written,
                    "end": written + len(part),
                    "boxes": [box(line) for line in sources],
                })
            written += len(part) + 2

    def flush() -> None:
        if para:
            emit(reflow(para), para_lines)
            para.clear()
            para_lines.clear()

    for i, ln in enumerate(lines):
        if ln.page != page:
            flush()
            page = ln.page
            prev = None
            emit(f"<!-- PAGE:{page} -->")

        if ln.rows:
            flush()
            emit(_render_table(ln), [ln])
        elif ln.is_statblock_name:
            flush()
            offsets[i] = written
            emit(f"{'#' * STATBLOCK_NAME_LEVEL} {ln.text}", [ln])
        elif ln.is_heading:
            flush()
            emit(f"{'#' * ln.heading_level} {ln.text}", [ln])
        elif ln.is_statblock_section:
            flush()
            emit(f"###### {ln.text}", [ln])
        else:
            if prev is not None and (ln.column != prev.column or ln.starts_paragraph):
                flush()
            para.append(_normalize_ws(ln.markup))
            para_lines.append(ln)
        prev = None if (ln.is_heading or ln.is_statblock_section or ln.rows) else ln

    flush()
    return "\n\n".join(parts), offsets, anchors


# A line's box is built from its baseline and type size, not from the
# reported bbox: on 95 of the 107 lines of a typical page PyMuPDF inflates
# the vertical extent to 56pt, which is the same unreliability that makes
# the whole pipeline order by baseline.  Horizontal extent *is* trustworthy
# — column detection and table cells already depend on it.
ASCENT = 0.80   # em above the baseline
DESCENT = 0.24  # em below it


def box(line: Line) -> dict:
    """
    One line's rectangle, in PDF points with the origin at the top left.

    PyMuPDF's convention, and also pdf.js's viewport convention, so the
    browser draws these by scaling alone — no axis flip, no page height.
    """
    return {
        "page": line.page,
        "x0": round(line.x0, 1),
        "y0": round(line.baseline - ASCENT * line.max_size, 1),
        "x1": round(line.x1, 1),
        "y1": round(line.baseline + DESCENT * line.max_size, 1),
    }


def _table_columns(anchor: Line) -> list[float]:
    """
    Cluster every cell's left edge into the table's column positions.

    Clustering is on the *gap* between adjacent x values, not on distance
    from the cluster's first member: cells in one column drift by a few
    points (numeric columns are right-aligned) while real columns sit tens
    of points apart, so a gap threshold separates them cleanly.
    """
    xs = sorted(x for r in anchor.rows for x in r.cell_x)
    if not xs:
        return []
    cols = [xs[0]]
    for prev, x in pairwise(xs):
        if x - prev > COLUMN_TOLERANCE:
            cols.append(x)
    return cols


def _render_table(anchor: Line) -> str:
    """
    Render a table anchor as a markdown pipe table.

    Cells are placed by their x position rather than by order, so a row that
    leaves a column empty stays aligned.  A row that puts nothing in the
    first column is a wrapped continuation of the row above (SRD tables wrap
    long Properties cells) and is folded back into it.
    """
    cols = _table_columns(anchor)
    grid: list[list[str]] = []

    for r in anchor.rows:
        row = [""] * len(cols)
        for text, x in zip(r.cells, r.cell_x):
            idx = min(range(len(cols)), key=lambda i: abs(cols[i] - x))
            cell = _normalize_ws(text).replace("|", r"\|")
            row[idx] = f"{row[idx]} {cell}".strip() if row[idx] else cell
        if grid and not row[0] and any(row):
            for i, cell in enumerate(row):
                if cell:
                    # A cell wraps mid-word just as a paragraph does, so the
                    # continuation is joined the same way — "Athlet-" + "ics".
                    grid[-1][i] = reflow([grid[-1][i], cell]).strip()
        else:
            grid.append(row)

    if not grid:
        return ""
    header, body = grid[0], grid[1:]
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join(["---"] * len(cols)) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(out)


def _normalize_ws(text: str) -> str:
    return re.sub(r"[\t  ]+", " ", text).strip()


def _splice_emphasis(out: str, piece: str) -> str:
    """
    Join two wrapped lines, mending an emphasis run broken across the break.

    A spell subtitle set over two lines arrives as
    ``_Level 2 Abjuration (Bard, Cleric,_`` + ``_Ranger)_``: the run is closed
    at the end of one line and reopened at the start of the next.  Left alone
    it reads as two separate italic runs, and every parser downstream sees a
    subtitle it cannot match.  Only the join between two lines is examined,
    so genuinely adjacent runs on one line are untouched.
    """
    for marker in ("**", "_"):
        if out.endswith(marker) and piece.startswith(marker):
            return f"{out[: -len(marker)]} {piece[len(marker):]}"
    return f"{out} {piece}"


def reflow(chunk: list[str]) -> str:
    """Join wrapped lines, healing words split by a trailing hyphen."""
    out = ""
    for piece in chunk:
        piece = piece.strip()
        if not piece:
            continue
        if not out:
            out = piece
        else:
            m = _HYPHEN_BREAK_RE.search(out)
            if not m:
                out = _splice_emphasis(out, piece)
                continue
            # Drop the hyphen and glue the halves.  When the break falls
            # inside an emphasis run the run is closed on one line and
            # reopened on the next; splice those markers out so the healed
            # word stays a single emphasised token.
            markers = m.group(2)
            head = out[: m.start()] + m.group(1)
            if markers and piece.startswith(markers):
                out = head + piece[len(markers):]
            else:
                out = head + markers + piece
    return unicodedata.normalize("NFC", out)
