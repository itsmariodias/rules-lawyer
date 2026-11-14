"""Lines to blocks in reading order: headings, paragraphs, lists, contents, tables, sidebars."""

from __future__ import annotations

import re
from collections.abc import Callable, Hashable
from dataclasses import replace

from rules_lawyer.srd.model import (
    Block,
    Contents,
    Entry,
    Heading,
    ListBlock,
    Paragraph,
    Run,
    Sidebar,
    Table,
    add_page,
)
from rules_lawyer.srd.reading.pages import (
    TABLE_NOTE,
    Line,
    boxes_of,
    column_key,
    pages_of,
)
from rules_lawyer.srd.reading.statblock import is_stat_line, is_title, stat_block
from rules_lawyer.srd.reading.tables import (
    extend_table,
    is_table_line,
    table,
    table_end,
    table_run,
    wraps_field,
)
from rules_lawyer.srd.reading.text import is_bold, runs_of

# One heading is set in the face's small caps, capitals 12pt and the rest
# 8.4pt ("Acid Splash", page 107); its text extracts in mixed case.
HEADING_FONTS = ("GillSans-SemiBold", "GillSans-SemiBold-SC700")
HEADING_LEVELS = {26.0: 1, 18.0: 2, 14.0: 3, 12.0: 4, 10.5: 5}
# A level 5 heading directly above a table is the table's caption (page 5).
CAPTION_LEVEL = 5
# Sidebar titles are small caps (GillSans-Bold-SC700, page 5).
SMALL_CAPS = "SC700"
# A list of names printed as a grid at the column's edge, read down each
# column (pages 11, 12, 176, 177, 179; alphabetical that way). The same font
# indented is a formula or starting equipment (pages 22, 83).
TERM_FONT = ("GillSans", 10.0)
# Its labels in a grid of abbreviations and their meanings (page 176).
KEY_FONT = ("GillSans-SemiBold", 10.0)
# Baseline step inside a paragraph, in ems: 12pt for 10pt Cambria (page 1).
LINE_STEP = 1.2
# Extra step that starts a paragraph: page 1 steps 12pt within, 17.4 to 24
# between.
PARAGRAPH_SLACK = 2.0
# How far right of its column's edge a line must start to count as indented;
# page 1 indents by 8pt, the contents by 9, list items hang by 11.5.
INDENT = 4.0
# List items: "1:" or a bullet, then a tab (22 numbered, 143 bulleted).
_MARKER = re.compile(r"^(?:(?P<number>\d+):|•)\t")
_MARKER_TEXT = re.compile(r"^(?:\d+:|•)\s*")
_SENTENCE_END = re.compile(r"[.!?:][”’)]*$")
# A contents entry: text, a dotted leader, a page number. Two entries on page 2
# have a one-dot leader ("Oath of Devotion.56"), so one dot counts after a
# letter. Over the whole book this matches only pages 2 to 4.
_ENTRY = re.compile(r"^(?P<text>.*?\S)\s*(?:\.{2,}|(?<=[A-Za-z’”])\.)\s*(?P<page>\d+)\s*$")


def read_blocks(lines: list[Line], hyphenated: set[str]) -> list[Block]:
    """Turn lines into blocks in reading order.

    The lines are the whole book, so a paragraph goes on across column and
    page breaks; each block records the pages it is printed on. Tables,
    sidebars and stat blocks are floats: one met while a paragraph or list is
    open is placed after it ends, so it never splits it (Fixed Hit Points by
    Class falls between steps 2 and 3 of Gaining a Level, page 23).

    Args:
        lines: Every page's lines from ``read_pages``, page 1 first.
        hyphenated: Output of ``compounds``, for undoing hyphenation.

    Returns:
        The blocks in reading order.
    """
    blocks: list[Block] = []
    para: list[Line] = []
    floats: list[Block] = []
    heading_line: Line | None = None

    def end_paragraph(flush: bool = True) -> None:
        if para:
            blocks.append(paragraph(para, hyphenated))
            para.clear()
        if flush:
            blocks.extend(floats)
            floats.clear()

    def place(block: Block) -> None:
        open_list = bool(blocks) and isinstance(blocks[-1], ListBlock)
        target = floats if para or open_list else blocks
        if target and continues_table(target[-1], block):
            extend_table(target[-1], block)
        else:
            target.append(block)

    i = 0
    while i < len(lines):
        line = lines[i]
        level = heading_level(line)
        caption = caption_lines(lines, i)
        if line.frame is not None:
            group = take(lines, i, lambda other: other.frame is not None, same=frame_key)
            place(sidebar(group, hyphenated))
            i += len(group)
        elif is_title(line):
            group = [line] + take(lines, i + 1, is_stat_line)
            place(stat_block(group, hyphenated, read_blocks))
            i += len(group)
        elif caption or (is_table_line(line) and not wraps_field(lines, i)):
            group = table_run(lines, i + len(caption))
            group = group[:table_end(group)]
            built = table(runs_of(caption, hyphenated), group, hyphenated)
            built.boxes[:0] = boxes_of(caption)
            place(built)
            i += len(caption) + len(group)
        elif is_term_line(line):
            end_paragraph()
            group = take(lines, i, is_term_line, same=column_key)
            blocks.append(term_list(group))
            i += len(group)
        elif is_key_line(line) and sum(s.face == KEY_FONT for s in line.spans) > 1:
            end_paragraph()
            group = take(lines, i, is_key_line, same=column_key)
            blocks.append(key_list(group))
            i += len(group)
        elif level is not None:
            end_paragraph()
            last = blocks[-1] if blocks else None
            if isinstance(last, Heading) and last.level == level and continues(heading_line, line):
                last.text = f"{last.text} {line.text.strip()}"
                last.boxes += boxes_of([line])
            else:
                blocks.append(Heading(level, line.text.strip(), line.page, boxes=boxes_of([line])))
            heading_line = line
            i += 1
        elif _ENTRY.match(line.text.strip()):
            # Lines just above an entry, less indented, are its start wrapped.
            wrapped = list(para) if para and line.x0 > para[-1].x0 else []
            if not wrapped:
                end_paragraph()
            para.clear()
            add_entry(blocks, contents_entry(wrapped + [line], hyphenated), wrapped + [line])
            i += 1
        elif _MARKER.match(line.text):
            end_paragraph(flush=bool(para) or not continues_list(blocks, line))
            item = item_lines(lines, i)
            add_item(blocks, item, hyphenated)
            i += len(item)
        else:
            if not para or starts_paragraph(para, line):
                end_paragraph()
            para.append(line)
            i += 1
        if level is None:
            heading_line = None
    end_paragraph()
    return blocks


def caption_lines(lines: list[Line], start: int) -> list[Line]:
    """The level 5 heading lines from ``start`` if a table follows them, else none.

    A caption may wrap ("Multiclass Spellcaster: / Spell Slots per Spell
    Level", page 26).

    Args:
        lines: The book's lines.
        start: Where the caption would begin.

    Returns:
        The caption's lines, or empty if no table follows in the same column.
    """
    end = start
    while (end < len(lines) and heading_level(lines[end]) == CAPTION_LEVEL
           and (end == start or continues(lines[end - 1], lines[end]))):
        end += 1
    follows = (end > start and end < len(lines) and is_table_line(lines[end])
               and column_key(lines[end]) == column_key(lines[start]))
    return lines[start:end] if follows else []


def take(lines: list[Line], start: int, keep: Callable[[Line], bool],
         same: Callable[[Line], Hashable] | None = None) -> list[Line]:
    """The run of lines from ``start`` that all belong together.

    Args:
        lines: The book's lines.
        start: The first line of the run.
        keep: Whether a line can be in the run.
        same: If given, every line must give what the first line gives.

    Returns:
        The lines from ``start`` up to the first that fails either test.
    """
    end = start
    while (end < len(lines) and keep(lines[end])
           and (same is None or same(lines[end]) == same(lines[start]))):
        end += 1
    return lines[start:end]


def frame_key(line: Line) -> tuple[int, int | None]:
    """Which sidebar frame a line is printed in.

    Args:
        line: A line of the book.

    Returns:
        Its page and frame index (None outside a frame).
    """
    return line.page, line.frame


def ends_sentence(line: Line) -> bool:
    """Whether the line's text ends a sentence (or a clause before a colon).

    Args:
        line: A line of the book.

    Returns:
        True if it ends in ".", "!", "?" or ":", closing quotes or brackets allowed after.
    """
    return bool(_SENTENCE_END.search(line.text.rstrip()))


def heading_level(line: Line) -> int | None:
    """The line's heading level, from its font and size.

    Args:
        line: A line of the book.

    Returns:
        1 to 5 if every span is heading type at a heading size, else None.
    """
    if all(s.font in HEADING_FONTS for s in line.spans):
        return HEADING_LEVELS.get(line.size)
    return None


def continues(prev: Line | None, line: Line) -> bool:
    """Whether ``line`` is the next line of the same column after ``prev``.

    Args:
        prev: The line before, or None.
        line: The line that may follow it.

    Returns:
        True if both share page, column and frame, and ``line`` sits within a line step below ``prev``.
    """
    return (prev is not None
            and (prev.page, prev.column, prev.frame) == (line.page, line.column, line.frame)
            and 0 < line.baseline - prev.baseline <= LINE_STEP * line.size + PARAGRAPH_SLACK)


def continues_across(prev: Line, line: Line, hanging: bool) -> bool:
    """Whether ``line``, atop the next column or page, carries on the paragraph ``prev`` ended.

    It does unless ``prev`` ends a sentence and the next word would have fitted
    on it: line breaking fills a line while the next word fits. A hanging
    paragraph goes on only with an indented line, any other only at the edge.

    Args:
        prev: The last line of the paragraph so far.
        line: The first line of the next column or page.
        hanging: Whether the paragraph is a hanging one (``is_hanging``).

    Returns:
        True if ``line`` continues the paragraph.
    """
    next_column = (prev.page, prev.column + 1)
    next_page = (prev.page + 1, 0)
    if column_key(line) not in (next_column, next_page):
        return False
    if line.frame != prev.frame or is_indented(line) != hanging:
        return False
    if not ends_sentence(prev):
        return True
    span = line.spans[0]
    char = (span.x1 - span.x0) / max(len(span.text), 1)
    return prev.x1 + char * (len(line.text.split()[0]) + 1) > prev.right


def starts_paragraph(para: list[Line], line: Line) -> bool:
    """Whether ``line`` begins a new paragraph after the lines of ``para``.

    Most paragraphs start with an indent, and a bold lead ("**_Squares._**",
    page 13) always starts one. A hanging paragraph ("**Weapons.** Anyone
    can...", page 9) starts at the edge with a bold lead and indents the rest,
    so in it a line back at the edge starts the next.

    Args:
        para: The open paragraph's lines, at least one.
        line: The line after them.

    Returns:
        True if ``line`` starts a paragraph of its own.
    """
    prev = para[-1]
    span = line.spans[0]
    # Each note under a table starts with its marker ("*", "†", page 192).
    if span.size <= TABLE_NOTE and span.text.startswith(("*", "†")):
        return True
    # A lead wrapped onto a second line ("...after a Long / Rest).", page 131)
    # leaves the line before ending in bold. After a break too: "**Range:**
    # Touch" ends a column, "**Components:**" heads the next (page 151).
    if (has_lead(line) or is_formula(line)) and not is_bold(prev.spans[-1]):
        return True
    if continues(prev, line):
        if len(para) == 1 and has_lead(prev) and not is_indented(prev):
            return False
        if is_hanging(para):
            return not is_indented(line)
        # A sentence ends a paragraph: after "**Aberrations** are ... abo-" the
        # indented "leths and cloakers." hangs (page 254).
        return is_indented(line) and not is_indented(prev) and ends_sentence(prev)
    # One line into a hanging paragraph, a break may come before the indent shows
    # ("**Variants:** ... dul-" / "cimer", page 94).
    hanging = is_hanging(para) or (len(para) == 1 and is_bold(prev.spans[0])
                                   and not is_indented(prev) and not ends_sentence(prev))
    return not continues_across(prev, line, hanging)


def continues_table(prev: Block, block: Block) -> bool:
    """Whether ``block`` is the rest of table ``prev``: no caption, the header repeated.

    A table broken by a column or page break prints its header again on the
    other side (Actions, pages 9 and 10).

    Args:
        prev: The block placed last.
        block: The block about to be placed.

    Returns:
        True if both are tables and ``block`` goes on with ``prev``.
    """
    return (isinstance(prev, Table) and isinstance(block, Table) and not block.caption
            and block.header == prev.header)


def has_lead(line: Line) -> bool:
    """Whether the line starts with a bold run ending a sentence, plain text after it.

    Args:
        line: A line of the book.

    Returns:
        True for a lead such as "**Weapons.** Anyone can...".
    """
    first = line.spans[0]
    # The stop may be set plain after the bold ("**Touch**.", page 105).
    lead = first.text.rstrip() + (line.spans[1].text[:1] if len(line.spans) > 1 else "")
    return (len(line.spans) > 1 and is_bold(first)
            and bool(_SENTENCE_END.search(first.text.rstrip()) or _SENTENCE_END.search(lead))
            and not all(is_bold(s) for s in line.spans))


def is_formula(line: Line) -> bool:
    """Whether the line sets out a formula: a bold label, then "=".

    As in "**Spell save DC** = 8 + ..." (page 23) and "**Miles per day**
    (Normal pace) = ..." (page 192).

    Args:
        line: A line of the book.

    Returns:
        True if an "=" follows the bold label in the line's first sentence.
    """
    return (len(line.spans) > 1 and is_bold(line.spans[0])
            and "=" in "".join(s.text for s in line.spans[1:]).split(".")[0])


def is_hanging(para: list[Line]) -> bool:
    """Whether the paragraph has a bold lead at the edge and indents its later lines.

    Args:
        para: A paragraph's lines.

    Returns:
        True for a paragraph of two or more lines laid out that way.
    """
    # The bold need not end a sentence: "**Aberrations** are ..." (page 254).
    return (len(para) > 1 and len(para[0].spans) > 1 and is_bold(para[0].spans[0])
            and not is_indented(para[0]) and is_indented(para[1]))


def is_indented(line: Line) -> bool:
    """Whether the line starts right of its column's edge.

    Args:
        line: A line with its column's ``left`` edge set.

    Returns:
        True if it starts more than ``INDENT`` right of the edge.
    """
    return line.x0 - line.left > INDENT


def is_term_line(line: Line) -> bool:
    """Whether the line is a row of a grid of names: term type, at its column's edge.

    Args:
        line: A line of the book.

    Returns:
        True if every span is ``TERM_FONT`` and the line is neither framed nor indented.
    """
    return (line.frame is None and not is_indented(line)
            and all(s.face == TERM_FONT for s in line.spans))


def term_list(lines: list[Line]) -> ListBlock:
    """A grid of names as a bulleted list, read down each column in turn.

    Args:
        lines: The grid's lines, from ``take`` with ``is_term_line``.

    Returns:
        An unordered list, one name per item.
    """
    edges = sorted({round(s.x0) for line in lines for s in line.spans})
    spans = sorted((s for line in lines for s in line.spans),
                   key=lambda s: edges.index(round(s.x0)))
    return ListBlock(False, [[Paragraph([Run(s.text.strip())], [lines[0].page])] for s in spans],
                     pages_of(lines), boxes=boxes_of(lines))


def is_key_line(line: Line) -> bool:
    """Whether the line is in a grid of labels and meanings: label and term type only.

    Args:
        line: A line of the book.

    Returns:
        True if every span is ``KEY_FONT`` or ``TERM_FONT`` and the line is not framed.
    """
    return line.frame is None and all(s.face in (KEY_FONT, TERM_FONT) for s in line.spans)


def key_list(lines: list[Line]) -> ListBlock:
    """A grid of labels and meanings as a bulleted list, read down each half in turn.

    It starts on a line with a label in each half ("AC Armor Class", "M Material
    component", page 176). The halves set their lines apart, and a meaning
    wraps onto a line of its own ("Nonplayer / character").

    Args:
        lines: The grid's lines, from ``take`` with ``is_key_line``.

    Returns:
        An unordered list, one bold label and its meaning per item.
    """
    halves = [s.x0 for s in lines[0].spans if s.face == KEY_FONT]
    entries: list[list[list[str]]] = [[] for _ in halves]
    for line in lines:
        for span in line.spans:
            half = entries[max(i for i, x in enumerate(halves) if x <= span.x0 + 0.5)]
            if span.face == KEY_FONT:
                half.append([span.text.strip()])
            else:
                half[-1].append(span.text.strip())
    pages = pages_of(lines)
    items = [[Paragraph([Run(label, bold=True), Run(" " + " ".join(meaning))], pages)]
             for half in entries for label, *meaning in half]
    return ListBlock(False, items, pages, boxes=boxes_of(lines))


def item_lines(lines: list[Line], start: int) -> list[Line]:
    """A list item: its marker line and the indented lines hanging under it.

    Args:
        lines: The book's lines.
        start: The item's marker line.

    Returns:
        The item's lines, the marker line first.
    """
    item = [lines[start]]
    for line in lines[start + 1:]:
        if (line.frame is not None or heading_level(line) is not None or _MARKER.match(line.text)
                or not is_indented(line) or not continues(item[-1], line)):
            break
        item.append(line)
    return item


def paragraph(lines: list[Line], hyphenated: set[str]) -> Paragraph:
    """Join a paragraph's lines into runs.

    Args:
        lines: The paragraph's lines.
        hyphenated: Output of ``compounds``, for undoing hyphenation.

    Returns:
        The paragraph, a quote if every line is indented and it is not a formula.
    """
    # A formula is centred, so indented, but displayed rather than quoted.
    quote = (len(lines) > 1 and all(is_indented(line) for line in lines)
             and not is_formula(lines[0]))
    return Paragraph(runs_of(lines, hyphenated), pages_of(lines), "quote" if quote else None,
                     boxes=boxes_of(lines))


def continues_list(blocks: list[Block], line: Line) -> bool:
    """Whether the item ``line`` starts adds to the list just before it.

    Args:
        blocks: The blocks read so far.
        line: A list item's marker line.

    Returns:
        True if the last block is a list of the same kind, numbered or bulleted.
    """
    last = blocks[-1] if blocks else None
    ordered = _MARKER.match(line.text).group("number") is not None
    return isinstance(last, ListBlock) and last.ordered == ordered


def add_item(blocks: list[Block], lines: list[Line], hyphenated: set[str]) -> None:
    """Add a list item, continuing the list just before it if it is the same kind.

    Args:
        blocks: The blocks read so far; the item is added in place.
        lines: The item's lines, from ``item_lines``.
        hyphenated: Output of ``compounds``, for undoing hyphenation.
    """
    number = _MARKER.match(lines[0].text).group("number")
    runs = runs_of(lines, hyphenated)
    runs[0].text = _MARKER_TEXT.sub("", runs[0].text)
    item: list[Block] = [Paragraph([r for r in runs if r.text], pages_of(lines))]
    if continues_list(blocks, lines[0]):
        last = blocks[-1]
        last.items.append(item)
        add_page(last.pages, lines[0].page)
        last.boxes += boxes_of(lines)
    else:
        blocks.append(ListBlock(number is not None, [item], pages_of(lines), int(number) if number else 1,
                                boxes=boxes_of(lines)))


def sidebar(lines: list[Line], hyphenated: set[str]) -> Sidebar:
    """A sidebar: its small-caps title, then its other lines read as blocks.

    Args:
        lines: Every line inside one frame.
        hyphenated: Output of ``compounds``, for undoing hyphenation.

    Returns:
        The sidebar, its title empty if the first line is not small caps.
    """
    has_title = all(SMALL_CAPS in s.font for s in lines[0].spans)
    title = runs_of(lines[:1], hyphenated) if has_title else []
    body = [replace(line, frame=None) for line in lines[1 if has_title else 0:]]
    return Sidebar(title, read_blocks(body, hyphenated), pages_of(lines), boxes=boxes_of(lines))


def add_entry(blocks: list[Block], entry: Entry, lines: list[Line]) -> None:
    """Add a contents entry, continuing the contents block just before it.

    Args:
        blocks: The blocks read so far; the entry is added in place.
        entry: The entry, from ``contents_entry``.
        lines: The lines it is printed on.
    """
    if blocks and isinstance(blocks[-1], Contents):
        blocks[-1].entries.append(entry)
        add_page(blocks[-1].pages, lines[-1].page)
        blocks[-1].boxes += boxes_of(lines)
    else:
        blocks.append(Contents([entry], [lines[-1].page], boxes=boxes_of(lines)))


def contents_entry(lines: list[Line], hyphenated: set[str]) -> Entry:
    """One contents entry from its lines, the last ending in leader and page.

    Args:
        lines: The entry's lines.
        hyphenated: Output of ``compounds``, for undoing hyphenation.

    Returns:
        The entry: level 1 if bold, 3 if indented, else 2.
    """
    runs = runs_of(lines, hyphenated)
    found = _ENTRY.match(runs[-1].text)
    runs[-1].text = found.group("text")
    if runs[0].bold:
        level = 1
    elif is_indented(lines[0]):
        level = 3
    else:
        level = 2
    return Entry([r for r in runs if r.text], int(found.group("page")), level)
