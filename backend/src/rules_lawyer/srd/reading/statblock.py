"""Stat blocks: told apart by their type, read into name, fields, scores and sections.

A stat block's type is fixed and its own: Optima (only stat blocks use it,
pages 109-364), small GillSans for the ability scores, and plain GillSans
12pt section headers. Its title is GillSans-SemiBold 14.8pt (336).
"""

from __future__ import annotations

from collections.abc import Callable

from rules_lawyer.srd.model import Block, Field, Paragraph, Run, StatBlock, StatSection
from rules_lawyer.srd.reading.pages import Line, boxes_of, pages_of
from rules_lawyer.srd.reading.text import runs_of

TITLE_FONT = ("GillSans-SemiBold", 14.8)
# Each field starts a line with its label: AC, HP, Speed, Skills, Senses,
# Languages, CR, ...
FIELD_FONT = ("Optima-Bold", 9.0)
# "Traits", "Actions", "Bonus Actions", "Reactions", "Legendary Actions" (666).
SECTION_FONT = ("GillSans", 12.0)
# The ability scores sit under "MOD SAVE" labels set this small, the names in
# small caps beside the values ("S" + "tr" 21 +5 +5); one name is bold ("Con",
# page 340).
LABEL_FONT = ("GillSans", 6.0)
SCORE_FONTS = (("GillSans", 9.8), ("GillSans-Bold", 9.8),
               ("GillSans-SemiBold-SC700", 9.8), ("GillSans-SemiBold-SC700", 6.8))


def is_title(line: Line) -> bool:
    """Whether the line is a stat block's title."""
    return all(s.face == TITLE_FONT for s in line.spans)


def is_stat_line(line: Line) -> bool:
    """Whether the line is in a stat block's type."""
    return line.frame is None and all(
        s.font.startswith("Optima") or s.face in (SECTION_FONT, LABEL_FONT, *SCORE_FONTS)
        for s in line.spans)


def stat_block(lines: list[Line], hyphenated: set[str],
               read: Callable[[list[Line], set[str]], list[Block]]) -> StatBlock:
    """Read a stat block from its title and the lines in its type after it.

    Args:
        lines: The title line, then the stat block's lines in reading order.
        hyphenated: Output of ``compounds``, for undoing hyphenation.
        read: How lines become paragraphs (``read_blocks``), for the entries.

    Returns:
        The stat block.

    Raises:
        ValueError: The ability scores are not after Speed, or an entry is not a
            paragraph.
    """
    subtitle: list[Line] = []
    fields: list[list[Line]] = []
    scores: list[Line] = []
    above = 0          # field lines before the scores
    sections: list[tuple[str, list[Line]]] = []
    for line in lines[1:]:
        font = line.spans[0].face
        if all(s.face == SECTION_FONT for s in line.spans):
            sections.append((line.text.strip(), []))
        elif sections:
            sections[-1][1].append(line)
        elif font == FIELD_FONT:
            fields.append([line])
        elif font in (LABEL_FONT, *SCORE_FONTS):
            above = above or len(fields)
            scores.append(line)
        elif fields:
            fields[-1].append(line)
        else:
            subtitle.append(line)
    top = [f for group in fields[:above] for f in fields_of(runs_of(group, hyphenated))]
    if not top or top[-1].label != "Speed":
        raise ValueError(f"page {lines[0].page}: {lines[0].text.strip()}'s scores are not after Speed")
    rest = [f for group in fields[above:] for f in fields_of(runs_of(group, hyphenated))]
    return StatBlock(lines[0].text.strip(), runs_of(subtitle, hyphenated), top + rest,
                     ability_rows(scores), [StatSection(title, entries(body, hyphenated, read))
                                            for title, body in sections],
                     pages_of(lines), boxes=boxes_of(lines))


def fields_of(runs: list[Run]) -> list[Field]:
    """The fields in a field line's runs: each bold run is a label ("AC 17 Initiative +7")."""
    fields: list[Field] = []
    for run in runs:
        if run.bold:
            fields.append(Field(run.text.strip(), []))
        else:
            fields[-1].value.append(Run(run.text, run.bold, run.italic))
    for field in fields:
        field.value[0].text = field.value[0].text.lstrip()
        field.value[-1].text = field.value[-1].text.rstrip()
        field.value = [r for r in field.value if r.text]
    return fields


def entries(lines: list[Line], hyphenated: set[str],
            read: Callable[[list[Line], set[str]], list[Block]]) -> list[Paragraph]:
    """A section's entries, read as paragraphs."""
    blocks = read(lines, hyphenated)
    for block in blocks:
        if not isinstance(block, Paragraph):
            raise ValueError(f"page {lines[0].page}: a stat block entry is a {type(block).__name__}")
    return blocks


def ability_rows(lines: list[Line]) -> list[list[str]]:
    """The ability scores as rows of name, score, MOD and SAVE, in the book's order.

    Args:
        lines: The "MOD SAVE" labels, then the lines of scores (three abilities
            each).

    Returns:
        One row per ability.

    Raises:
        ValueError: An ability has other than a score, a modifier and a save.
    """
    rows: list[list[str]] = []
    in_name = False
    for line in lines:
        if all(s.face == LABEL_FONT for s in line.spans):
            continue
        for span in line.spans:
            text = span.text.strip()
            if text.isalpha():
                if in_name:
                    rows[-1][0] += text
                else:
                    rows.append([text])
            else:
                rows[-1].extend(span.text.split())
            in_name = text.isalpha() or (in_name and not text)
    for row in rows:
        if len(row) != 4:
            raise ValueError(f"page {lines[0].page}: ability {row} is not a score, MOD and SAVE")
    return rows
