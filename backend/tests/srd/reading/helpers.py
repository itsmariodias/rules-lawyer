"""Builders for the lines the srd tests feed in."""

from __future__ import annotations

from dnd_graph_rag.srd.reading.pages import Line, Span

MARGIN = 63.0       # the left column's edge on a body page
RIGHT = 291.5       # how far page 5's left column reaches
CHAR = 4.5          # a rough width per character of 10pt Cambria


def line(baseline: float, *texts: str, x0: float = MARGIN, font: str = "Cambria",
         size: float = 10.0, column: int = 0, left: float = MARGIN, right: float = RIGHT,
         frame: int | None = None, page: int = 1) -> Line:
    """A line of one or more spans in one font, laid left to right."""
    spans, x = [], x0
    for text in texts:
        spans.append(Span(text, font, size, x, x + CHAR * len(text)))
        x += CHAR * len(text)
    return Line(page, baseline, spans, column, left, right, frame)
