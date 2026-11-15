"""A cited section's markdown slice and its page rectangles.

``srd_hierarchy.md`` and ``srd_hierarchy.anchors.json`` (about 4 MB together)
are read once per process.
"""

from __future__ import annotations

import json
from functools import lru_cache

from rules_lawyer.chat.retrieval import search
from rules_lawyer.config import anchors_path_for, get_settings, markdown_path_for
from rules_lawyer.srd.output.anchors import boxes_between


@lru_cache(maxsize=1)
def markdown() -> str:
    """The stage 1 markdown, cached.

    Returns:
        The whole of ``srd_hierarchy.md``.

    Raises:
        FileNotFoundError: It has not been generated.
    """
    return _read(markdown_path_for(get_settings().output_path), "markdown")


@lru_cache(maxsize=1)
def anchors() -> list[dict]:
    """The anchors file, cached.

    Returns:
        The anchors in document order; empty if the file is absent (artifacts
        predating it).
    """
    path = anchors_path_for(markdown_path_for(get_settings().output_path))
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _read(path, what: str) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"source {what} not found: {path} (run `uv run rules-lawyer parse` first)")
    return path.read_text(encoding="utf-8")


def excerpt(section_id: str, context: int = 0) -> dict | None:
    """A section's source text, page boxes and tree neighbours.

    Args:
        section_id: Dotted section id.
        context: Extra characters of markdown on each side of the section.

    A section covers all its subsections, so a top-level section's boxes can
    run to dozens of pages (87 for Monsters A-Z).

    Returns:
        ``text`` (the widened slice), ``highlight`` (the section's offsets
        within ``text``), ``boxes`` and ``pages`` (for the section alone),
        heading, type, labels, ``ancestors``, ``parent`` and ``children``.
        None if no such section.

    Raises:
        FileNotFoundError: The markdown has not been generated.
    """
    found = search.get_section(section_id)
    if found is None:
        return None
    passage, around = found

    if passage.char_start is None or passage.char_end is None:
        return {"section_id": section_id, "heading": passage.heading,
                "entity_type": passage.entity_type, "page": passage.page_start,
                "text": passage.content or "", "highlight": None,
                "boxes": [], "pages": [], **around}

    boxes = boxes_between(anchors(), passage.char_start, passage.char_end)
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
        "highlight": {"start": passage.char_start - start,
                      "end": passage.char_end - start},
        "boxes": boxes,
        "pages": sorted({box["page"] for box in boxes}),
        **around,
    }
