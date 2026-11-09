"""
Line-level PDF extraction in reading order, and its markdown rendering.

PyMuPDF's block order sometimes sorts a bottom-of-column fragment after the
facing column, which detached stat block lines from their creature.  So:

  1. extract every line with its bbox and span styles; drop the footer
  2. measure column frames from empty vertical strips, snapped to the
     book-wide grid
  3. lift tables out whole and rebuild cells from text x positions
  4. band the page on full-width lines; read each column top to bottom
  5. merge lines sharing a baseline (stat block ability grids)
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
# not GillSans-SemiBold, which is what separates them from real headings.
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
    """One visual line of the PDF, or a table anchor carrying its rows."""

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
    # edges; tables are rebuilt from these.
    cells: list[str] = field(default_factory=list)
    cell_x: list[float] = field(default_factory=list)
    table_id: int | None = None
    # Set on a table anchor line: the table's rows, already split into cells.
    rows: list[Line] = field(default_factory=list)
    # Shared by the lines of one float (a captioned table or a sidebar),
    # which ``place_floats`` moves as a unit.
    float_id: int | None = None

    @property
    def is_heading(self) -> bool:
        """Whether ``heading_level`` is set."""
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
    Left edge of each text frame, from empty strips in the x projection.

    Lines inside tables are excluded, since a table's internal gutters are not
    page columns.  A table tall enough to fill a column contributes its own
    left edge instead, as it leaves no loose lines to project.
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
    The most common frame set across the book.

    Args:
        frames_per_page: Each page's measured frame left edges.

    Returns:
        The book's column grid, used by ``snap_to_grid`` to correct pages
        whose undetected tables look like extra columns.
    """
    counts = Counter(tuple(round(f) for f in frames) for frames in frames_per_page)
    return [float(f) for f in counts.most_common(1)[0][0]]


def snap_to_grid(frames: list[float], grid: list[float]) -> list[float]:
    """
    Reconcile one page's measured frames with the book's grid.

    Args:
        frames: The page's measured frame left edges.
        grid: The result of ``document_grid``.

    Returns:
        ``grid`` when every frame is on it (a table spanning the gutter can
        hide a column); the on-grid frames when at least two match; otherwise
        ``frames`` unchanged, since the contents pages genuinely run three
        and four columns.
    """
    matched = [f for f in frames if any(abs(f - g) <= FRAME_SNAP for g in grid)]
    if len(matched) == len(frames):
        return grid
    return matched if len(matched) >= 2 else frames


def _column_of(x0: float, x1: float, frames: list[float]) -> int:
    """
    Index of the frame a line sits in, or -1 when it spans into the next.

    ``FRAME_SNAP`` slack on the left edge: a frame's measured edge is its
    leftmost content, so a table can start a few points left of it.
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

    Stat block ability grids and the ``AC … Initiative …`` line are printed
    as separate runs on one baseline.
    """
    if not lines:
        return []
    merged: list[Line] = []
    bucket: list[Line] = [lines[0]]
    for ln in lines[1:]:
        head = bucket[0]
        same_baseline = abs(ln.baseline - head.baseline) <= BASELINE_TOLERANCE
        # Font metrics make a heading's bbox overlap adjacent body text.
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
    Set ``starts_paragraph`` on lines in one column run.

    The modal baseline step is the run's leading (the book uses 9, 9.5 and
    10pt body text); a larger step or a leading tab starts a paragraph.
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
    Table regions on a page.

    Only the region is used: most SRD rows have no ruling lines, so the
    finder's cell split is wrong and cells are rebuilt from text x positions.
    """
    try:
        return [pymupdf.Rect(t.bbox) for t in page.find_tables().tables]
    except (ValueError, RuntimeError):
        # The finder fails on a few pages; those read as flowing text.
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
    Collapse a table region's lines into one anchor ``Line`` holding its rows.

    Only the anchor takes part in page ordering, so the table stays intact.
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
    Rejoin headings the PDF set over two lines.

    "Curses and Magical Contagions" and "Index of Stat Blocks" otherwise
    become sections called "Curses and" and "Index of Stat".  Two heading
    lines join when they share level and size, overlap horizontally, and
    sit one line apart.
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
TABLE_TEXT_MAX = 9.6      # table text is 9.2pt; body text 10pt
TABLE_ROW_REACH = 20.0    # how far outside a rect a stray row may sit


def _absorb_edge_rows(rows: list[Line], rect: pymupdf.Rect, free: list[Line]) -> list[Line]:
    """
    Reclaim rows just outside a table's detected rectangle.

    PyMuPDF bounds a table by its shaded rows, so an unshaded first or last
    row falls outside (the Bard cantrip list lost "Vicious Mockery").  A row
    qualifies when it is within ``TABLE_ROW_REACH`` of the rect and puts at
    least two fragments under the table's columns; prose is one fragment.

    Args:
        rows: Lines already inside the table.
        rect: The table's detected rectangle.
        free: Lines not in any table.  Absorbed lines are removed from it.

    Returns:
        The absorbed lines.
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
    Keep each table's caption directly ahead of it in reading order.

    Header rows printed between a caption and its table join the table
    first.  A full-width table's caption is then made full width: otherwise
    a caption at the foot of a column (e.g. "Apparatus of the Crab Levers",
    p210) is followed by the whole facing column before its table.  Only the
    nearest heading above, with nothing between in its column.
    """
    for anchor in anchors:
        # Rows reclaimed from outside the detected rectangle move its top.
        anchor.y0 = min([anchor.y0] + [r.baseline - ASCENT * r.max_size
                                       for r in anchor.rows])
        _absorb_header_rows(anchor, free)
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


def _absorb_header_rows(anchor: Line, free: list[Line]) -> None:
    """
    Move a table's header rows, printed between its caption and the
    detected rectangle, into its rows.

    The unshaded top header row ("Proficiency", "Spell Slots per Spell
    Level") falls outside the rectangle, and as one fragment per column
    it is not reclaimed by ``_absorb_edge_rows``.  It is set in the table's
    type size, below body text.  Only under a caption: a stat block's
    subtitle and AC line are small type above its ability table too.
    """
    reach = CAPTION_GAP + 2 * TABLE_ROW_REACH
    above = [
        l for l in free
        if l.heading_level == CAPTION_LEVEL and not l.is_statblock_name
        and (anchor.column == -1 or l.column == anchor.column)
        and 0 < anchor.y0 - l.baseline <= reach
    ]
    if not above:
        return
    caption = max(above, key=lambda l: l.baseline)
    between = [l for l in free
               if caption.baseline < l.baseline < anchor.y0
               and anchor.x0 - COLUMN_TOLERANCE <= l.x0
               and l.x1 <= anchor.x1 + COLUMN_TOLERANCE]
    header = [l for l in between
              if not l.is_heading and l.max_size < TABLE_TEXT_MAX]
    if not header or len(header) != len(between):
        return
    top = min(l.baseline - ASCENT * l.max_size for l in header)
    if top - caption.baseline > CAPTION_GAP:
        return
    for line in header:
        free.remove(line)
    rows = _merge_baselines(sorted(header, key=lambda l: (l.baseline, l.x0)))
    for row in rows:
        row.table_id = anchor.table_id
    anchor.rows[:0] = rows
    anchor.y0 = top
    anchor.baseline = rows[0].baseline


def _order_page(lines: list[Line], rects: list[pymupdf.Rect],
                frames: list[float], next_table_id: int) -> tuple[list[Line], int]:
    """
    Order one page: tables as units, bands split on full-width lines, and
    columns left to right within a band.

    Returns:
        The ordered lines and the next unused table id.
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
    """
    Extract every text line of the PDF in reading order.

    Args:
        pdf_path: The SRD PDF.

    Returns:
        Lines across all pages, tables collapsed to anchor lines, and each
        float moved to the section it belongs to (``place_floats``).
    """
    doc = pymupdf.open(str(pdf_path))

    rects_per_page = [_table_rects(doc[pno]) for pno in range(doc.page_count)]
    frames_per_page = [_page_frames(doc[pno], rects_per_page[pno])
                       for pno in range(doc.page_count)]
    grid = document_grid(frames_per_page)

    out: list[Line] = []
    table_id = 0
    float_id = 0
    for pno in range(doc.page_count):
        page, rects = doc[pno], rects_per_page[pno]
        frames = snap_to_grid(frames_per_page[pno], grid)
        ordered, table_id = _order_page(
            _raw_lines(page, pno + 1, frames), rects, frames, table_id
        )
        float_id = mark_floats(ordered, _sidebar_rects(page), float_id)
        out.extend(ordered)
    doc.close()
    _join_continued_tables(out)
    return place_floats(out)


# ---------------------------------------------------------------------------
# Floats: captioned tables and sidebars
# ---------------------------------------------------------------------------
# The book places tables and sidebars wherever they fit on the page, so in
# reading order one often lands mid-section, and the prose after it would
# become the content of its caption.  Each is lifted out and put back at a
# section boundary of the section it belongs to.

CAPTION_LEVEL = 5         # captions and sidebar titles are set at 10.5pt
SIDEBAR_FRAME = 0.3       # max fill component of a sidebar's dark frame
SIDEBAR_MIN_WIDTH = 100.0
SIDEBAR_MIN_HEIGHT = 20.0

_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _sidebar_rects(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """
    Sidebar boxes on a page.

    A sidebar is framed by a near-black filled rectangle under a light one;
    table shading is light grey only, so the dark fill tells them apart.
    """
    out = []
    for drawing in page.get_drawings():
        fill, rect = drawing.get("fill"), drawing["rect"]
        if (fill and max(fill) < SIDEBAR_FRAME
                and rect.width > SIDEBAR_MIN_WIDTH
                and rect.height > SIDEBAR_MIN_HEIGHT):
            out.append(pymupdf.Rect(rect))
    return out


def _inside(line: Line, rect: pymupdf.Rect) -> bool:
    cx = (line.x0 + line.x1) / 2
    return rect.x0 <= cx <= rect.x1 and rect.y0 <= line.baseline <= rect.y1


def mark_floats(ordered: list[Line], sidebars: list[pymupdf.Rect],
                next_id: int) -> int:
    """
    Give the lines of each float on one page a shared ``float_id``.

    A sidebar is every line inside its frame; a box without a title of its
    own continues the previous one (a sidebar can run across both columns).
    A captioned table is a level-5 heading followed directly by a table
    anchor; ``_join_continued_tables`` later adds what continues it.

    Args:
        ordered: One page's lines in reading order; mutated.
        sidebars: The page's sidebar frames.
        next_id: The first unused float id.

    Returns:
        The next unused float id.
    """
    current = None
    for rect in sorted(sidebars, key=lambda r: (r.x0, r.y0)):
        inside = [l for l in ordered if l.float_id is None and _inside(l, rect)]
        if not inside:
            continue
        if current is None or any(l.is_heading for l in inside):
            current, next_id = next_id, next_id + 1
        for line in inside:
            line.float_id = current

    for i, line in enumerate(ordered):
        if not line.rows or line.float_id is not None or i == 0:
            continue
        caption = ordered[i - 1]
        if (caption.heading_level != CAPTION_LEVEL or caption.is_statblock_name
                or caption.float_id is not None):
            continue
        caption.float_id = line.float_id = next_id
        next_id += 1
    return next_id


def _join_continued_tables(lines: list[Line]) -> None:
    """
    Extend each float's table over what continues it.

    A table can be printed in halves (Damage Types), run uncaptioned onto
    the next page ("Level 2 Bard Spells", p34), be split by the finder into
    several small tables ("Level 2 Cleric Spells", p39), or leave fragments
    of a row cut by a column break between its parts ("Prismatic Rays").
    So an uncaptioned table joins the float before it, and so does any text
    in table type size around it, footnotes included.  Without this the
    continuation stays behind when the first part is placed.
    """
    i = 0
    while i < len(lines):
        line = lines[i]
        if not (line.rows and line.float_id is not None):
            i += 1
            continue
        j = i + 1
        while j < len(lines) and lines[j].float_id is None and not lines[j].is_heading \
                and (lines[j].rows or lines[j].max_size < TABLE_TEXT_MAX):
            lines[j].float_id = line.float_id
            j += 1
        i = j


@dataclass
class _Section:
    """A heading in the line stream, as the section tree will see it."""

    index: int          # position in the stream
    level: int
    page: int
    body: str = ""      # its own prose, up to the next heading


def _effective_level(line: Line) -> int | None:
    """The level a line's heading is emitted at; None for content."""
    if line.is_statblock_name:
        return STATBLOCK_NAME_LEVEL
    return line.heading_level


def _sections(stream: list[Line]) -> list[_Section]:
    """Every heading of ``stream`` with the prose beneath it."""
    out: list[_Section] = []
    for i, line in enumerate(stream):
        level = _effective_level(line)
        if level is not None:
            out.append(_Section(i, level, line.page))
        elif out and not line.is_statblock_section:
            out[-1].body += " " + line.text
    return out


def _mentions(body: str, caption: str) -> bool:
    """Whether prose refers to a table by its caption ("the X table")."""
    name = r"\s+".join(map(re.escape, _TRAILING_PAREN_RE.sub("", caption).split()))
    return bool(name) and re.search(
        rf"\b{name}\W{{0,3}}\s+table", body, re.IGNORECASE
    ) is not None


def _owner(sections: list[_Section], at: int, page: int,
           caption: str | None) -> _Section | None:
    """
    The section a float at stream position ``at`` belongs to.

    The shallowest open section that refers to the table by name (a class's
    features section introduces its table, and its first feature mentions
    it again); failing that, the nearest section closed on this page or the
    one before that does; failing that, the deepest open section.  Only
    sections that can take a child heading (level below ``CAPTION_LEVEL``)
    qualify.
    """
    stack: list[_Section] = []
    closed: list[_Section] = []
    for section in sections:
        if section.index >= at:
            break
        while stack and stack[-1].level >= section.level:
            closed.append(stack.pop())
        stack.append(section)
    open_ = [s for s in stack if s.level < CAPTION_LEVEL]
    if caption:
        for section in open_:
            if _mentions(section.body, caption):
                return section
        for section in reversed(closed):
            if section.page < page - 1:
                break
            if section.level < CAPTION_LEVEL and _mentions(section.body, caption):
                return section
    return open_[-1] if open_ else None


def _boundaries(sections: list[_Section], owner: _Section,
                end: int) -> tuple[int, int, int]:
    """
    Where a float may go in its owner, and the level it must take there.

    Returns:
        The position after the owner's own prose (before its first child),
        the position after its whole subtree, and the level of the owner's
        children (one below the owner if it has none).  A float set at any
        other level would either adopt the children that follow it or, set
        shallower than they are, leave them stranded in the owner's prose.
    """
    later = [s for s in sections if s.index > owner.index]
    first = later[0].index if later else end
    close = next((s.index for s in later if s.level <= owner.level), end)
    inside = [s.level for s in later if s.index < close]
    return first, close, min(inside, default=owner.level + 1)


def place_floats(lines: list[Line]) -> list[Line]:
    """
    Move each float to a section boundary of the section it belongs to.

    A float goes to whichever boundary of its owner (see ``_owner``) is
    nearer where it was printed; a sidebar without a title always goes
    after the owner's own prose, since at the end of the subtree it would
    join the last subsection.  The prose the float interrupted closes
    up, so it is no longer read as the caption's content.  The title takes
    the level of the owner's children, so the float becomes one of them.

    Args:
        lines: Every line in reading order, floats marked by ``mark_floats``.

    Returns:
        The lines reordered; float lines are the same objects, re-levelled.
    """
    floats: dict[int, list[Line]] = {}
    origin: dict[int, int] = {}
    stream: list[Line] = []
    for line in lines:
        if line.float_id is None:
            stream.append(line)
        else:
            floats.setdefault(line.float_id, []).append(line)
            origin.setdefault(line.float_id, len(stream))

    sections = _sections(stream)
    placed: dict[int, list[Line]] = {}
    for float_id, members in floats.items():
        at = origin[float_id]
        heads = [l for l in members if l.is_heading]
        title = heads[0] if heads else None
        caption = title.text if title and any(l.rows for l in members) else None
        owner = _owner(sections, at, members[0].page, caption)
        if owner is None:
            placed.setdefault(at, []).extend(members)
            continue
        first, close, level = _boundaries(sections, owner, len(stream))
        if title is None or abs(at - first) <= abs(at - close):
            target = first
        else:
            target = close
        for line in heads:
            line.heading_level = min(CAPTION_LEVEL,
                                     level if line is title else level + 1)
        members[0].starts_paragraph = True
        placed.setdefault(target, []).extend(members)

    out: list[Line] = []
    for i, line in enumerate(stream):
        out.extend(placed.get(i, []))
        out.append(line)
    out.extend(placed.get(len(stream), []))
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

    Body lines are reflowed into paragraphs.  Stat block titles are emitted
    at ``STATBLOCK_NAME_LEVEL`` regardless of type size, so a creature
    printed inside a spell nests under it instead of outranking it.

    Args:
        lines: Output of ``extract_lines``.

    Returns:
        A tuple of the markdown; a map from the index in ``lines`` of each
        stat block title to its character offset in the markdown; and one
        anchor per emitted part, ``{"start", "end", "boxes"}``.  Anchors are
        per part because reflowing destroys character-level correspondence;
        section boundaries always fall on part boundaries.
    """
    parts: list[str] = []
    offsets: dict[int, int] = {}
    anchors: list[dict] = []
    para: list[str] = []
    para_lines: list[Line] = []
    page = None
    prev: Line | None = None
    # Running length of the joined output; parts are separated by "\n\n".
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


# Vertical extent comes from baseline and size: PyMuPDF reports 95 of 107
# lines on a typical page as 56pt tall.  Horizontal extent is reliable.
ASCENT = 0.80   # em above the baseline
DESCENT = 0.24  # em below it


def box(line: Line) -> dict:
    """
    One line's rectangle in PDF points, origin top left.

    That is also pdf.js's viewport convention, so the browser only scales.

    Args:
        line: A line or table anchor.

    Returns:
        ``{"page", "x0", "y0", "x1", "y1"}``, rounded to 0.1pt.
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
    Cluster cell left edges into column positions.

    Split on the gap between adjacent x values: right-aligned numeric cells
    drift a few points within a column, while columns sit tens apart.
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

    Cells are placed by x position so sparse rows stay aligned.  A row with
    an empty first cell is a wrapped continuation and folds into the row
    above.
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
                    # Cells hyphenate across wraps too: "Athlet-" + "ics".
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
    Join two wrapped lines, mending an emphasis run split across the break.

    ``_Level 2 Abjuration (Bard, Cleric,_`` + ``_Ranger)_`` becomes one italic
    run, which the spell subtitle parser requires.
    """
    for marker in ("**", "_"):
        if out.endswith(marker) and piece.startswith(marker):
            return f"{out[: -len(marker)]} {piece[len(marker):]}"
    return f"{out} {piece}"


def reflow(chunk: list[str]) -> str:
    """
    Join wrapped lines into one paragraph, healing hyphenated breaks.

    Args:
        chunk: Consecutive lines of markup.

    Returns:
        The joined text, NFC-normalised.
    """
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
            # If the hyphen sits inside an emphasis run that reopens on the
            # next line, drop the reopening markers too.
            markers = m.group(2)
            head = out[: m.start()] + m.group(1)
            if markers and piece.startswith(markers):
                out = head + piece[len(markers):]
            else:
                out = head + markers + piece
    return unicodedata.normalize("NFC", out)
