"""Lines to styled runs: style from fonts, lines joined, hyphenation undone."""

from __future__ import annotations

import re
from itertools import pairwise

from dnd_graph_rag.srd.model import Run
from dnd_graph_rag.srd.reading.pages import Line, Span, word_gap

_WORD = re.compile(r"[A-Za-z]+")
_COMPOUND = re.compile(r"[A-Za-z]+-[A-Za-z]+")
_URL_OPEN = re.compile(r"https?://\S*/$")
_DASH = "\u2014"
# Control characters print nothing; the PDF has three BELs (\x07) after list
# markers on page 19.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# A zero-width space after a line-end hyphen marks the hyphen as the word's
# own ("real-" / "world folklore", page 254); the book has two, the other at
# a cell's end.
_ZERO_WIDTH = "\u200b"
_SOFT_HYPHEN = "\u00ad"


def compounds(pages: list[list[Line]]) -> set[str]:
    """Every hyphenated word the book prints within a line, lowercased.

    A hyphen ending a line is kept only if the book prints that word with its
    hyphen elsewhere ("foot-wide"); otherwise it is a break between syllables.
    Of the 2,403 lines in the book ending in a hyphen before a lowercase word,
    25 end in such a word.

    Args:
        pages: Each page's lines.

    Returns:
        The set of hyphenated words.
    """
    return {w.lower() for lines in pages for line in lines for w in _COMPOUND.findall(line.text)}


def runs_of(lines: list[Line], hyphenated: set[str]) -> list[Run]:
    """The styled runs of consecutive lines, joined and whitespace-normalised.

    Args:
        lines: Lines read in order, as one piece of text.
        hyphenated: Output of ``compounds``.

    Returns:
        Runs with no empty text, adjacent runs differing in style.
    """
    runs: list[Run] = []
    for line in lines:
        if runs:
            join_line(runs, line, hyphenated)
        for before, span in zip([None] + line.spans, line.spans):
            if before and word_gap(before, span):
                append(runs, Run(" ", *style(span)))
            append(runs, Run(_CONTROL.sub("", span.text), *style(span)))
    for run in runs:
        run.text = re.sub(r"\s+", " ", run.text.replace(_ZERO_WIDTH, "").replace(_SOFT_HYPHEN, ""))
        # Style on punctuation alone shows nothing: an italic period after
        # plain "section" (page 24) would render as "_._".
        if not re.search(r"\w", run.text):
            run.bold = run.italic = False
    runs = merged(runs)
    for run, after in pairwise(runs):
        # A style ends with its word: the book sets one "s" upright after
        # italic "Cure Wound" (page 40), and markdown cannot close emphasis
        # inside a word.
        tail = _WORD.match(after.text) if re.search(r"[A-Za-z]$", run.text) else None
        if tail:
            run.text, after.text = run.text + tail.group(0), after.text[tail.end():]
        # A space at a styled run's edge belongs to its plain neighbour.
        if run.text.endswith(" ") and (run.bold or run.italic) and not (after.bold or after.italic):
            run.text, after.text = run.text[:-1], " " + after.text.lstrip()
        if after.text.startswith(" ") and (after.bold or after.italic) and not (run.bold or run.italic):
            run.text, after.text = run.text.rstrip() + " ", after.text[1:]
    if runs:
        runs[0].text = runs[0].text.lstrip()
        runs[-1].text = runs[-1].text.rstrip()
    return merged([r for r in runs if r.text])


def merged(runs: list[Run]) -> list[Run]:
    """Runs with each run of one style joined into one."""
    out: list[Run] = []
    for run in runs:
        append(out, run)
    return out


def join_line(runs: list[Run], line: Line, hyphenated: set[str]) -> None:
    """End the previous line in ``runs`` so ``line`` can follow it."""
    last = runs[-1]
    last.text = last.text.rstrip()
    if last.text.endswith("-" + _ZERO_WIDTH):
        return
    # A soft hyphen marks where a word may break; at a break it joins the halves
    # ("Meta" / "magic", page 66).
    if last.text.endswith(_SOFT_HYPHEN):
        last.text = last.text[:-1]
        return
    head = _WORD.match(line.text.lstrip())
    tail = re.search(r"([A-Za-z]+)-$", last.text)
    if tail and head:
        # Before a capital the hyphen is the word's own ("Three-Quarters",
        # page 15; "Shape-Shift", page 335): syllable breaks are lowercase.
        if head.group(0)[0].islower() and f"{tail.group(1)}-{head.group(0)}".lower() not in hyphenated:
            last.text = last.text[:-1]
        return
    # Beside a number the hyphen is the compound's ("15-" / "foot", page 98;
    # "10-by-" / "10-foot", page 173).
    if ((re.search(r"\w-$", last.text) and re.match(r"\d", line.text.lstrip()))
            or re.search(r"\d-$", last.text)):
        return
    # The book's two URLs are on page 1; one breaks after a slash.
    if _URL_OPEN.search(last.text):
        return
    # The book closes up its dashes: 176 mid-line, 2 spaced (page 13).
    if last.text.endswith(_DASH) or line.text.lstrip().startswith(_DASH):
        return
    last.text += " "


def append(runs: list[Run], run: Run) -> None:
    """Add a run, merging it into the last one when the style matches."""
    if runs and (runs[-1].bold, runs[-1].italic) == (run.bold, run.italic):
        runs[-1].text += run.text
    else:
        runs.append(run)


def style(span: Span) -> tuple[bool, bool]:
    """(bold, italic) from the font name: Cambria-BoldItalic, Optima-Bold, GillSans-SemiBold, ..."""
    name = span.font.split("-", 1)[-1] if "-" in span.font else ""
    return "Bold" in name, "Italic" in name


def is_bold(span: Span) -> bool:
    """Whether the span is set in a bold or semibold face."""
    return style(span)[0]
