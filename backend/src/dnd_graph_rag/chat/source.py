"""
A citation resolved to the book's own words, and to its place on the page.

A section node carries ``char_start``/``char_end`` into
``srd_hierarchy.md``, which is sliced for the text, and
``srd_hierarchy.anchors.json`` maps that same range to the rectangles of the
lines behind it, which the UI draws over a render of the page.

Both files are read once and cached: together they are about 4 MB, and every
citation in every conversation slices the same two.
"""

from __future__ import annotations

import json
from functools import lru_cache

from ..config import anchors_path_for, get_settings, markdown_path_for
from ..srd.pipeline import section_boxes
from . import retrieval


@lru_cache(maxsize=1)
def markdown() -> str:
    return _read(markdown_path_for(get_settings().output_path), "markdown")


@lru_cache(maxsize=1)
def anchors() -> list[dict]:
    """
    Page geometry per emitted part, in document order.

    Missing on an artifact generated before the anchors existed, which is a
    re-parse away rather than an error worth failing a citation over — so
    the caller gets no boxes and the text still resolves.
    """
    path = anchors_path_for(markdown_path_for(get_settings().output_path))
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _read(path, what: str) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"source {what} not found: {path} (run `uv run srd-parse` first)")
    return path.read_text(encoding="utf-8")


def excerpt(section_id: str, context: int = 0) -> dict | None:
    """
    The source text of one section, with the graph's own view of it.

    ``context`` widens the slice on both sides so the panel can show a
    citation in its surroundings; the offsets of the citation itself are
    returned alongside, so the caller can still highlight exactly it.
    """
    found = retrieval.get_section(section_id)
    if found is None:
        return None
    passage, around = found

    if passage.char_start is None or passage.char_end is None:
        return {"section_id": section_id, "heading": passage.heading,
                "entity_type": passage.entity_type, "page": passage.page_start,
                "text": passage.content or "", "highlight": None,
                "boxes": [], "pages": [], **around}

    boxes = section_boxes(anchors(), passage.char_start, passage.char_end)
    text = markdown()
    start = max(0, passage.char_start - context)
    end = min(len(text), passage.char_end + context)
    return {
        "section_id": section_id,
        "heading": passage.heading,
        "entity_type": passage.entity_type,
        "page": passage.page_start,
        "labels": passage.labels,
        "text": text[start:end],
        # Where the section sits inside the slice above, so a widened
        # excerpt can still dim everything that is not the citation.
        "highlight": {"start": passage.char_start - start,
                      "end": passage.char_end - start},
        # Always the citation's own range, never the widened one: the boxes
        # mark what was cited, not what is being shown around it.
        "boxes": boxes,
        "pages": sorted({box["page"] for box in boxes}),
        **around,
    }
