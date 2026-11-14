"""Sections to and from JSON. The JSON is the book; markdown is rendered from it."""

from __future__ import annotations

from ..model import SECTIONS, Section


def to_json(title: str, sections: list[Section]) -> dict:
    """The document as JSON-ready data.

    Args:
        title: The book's title, from its footers.
        sections: The book's top-level sections.

    Returns:
        ``{"title", "sections"}``.
    """
    return {"title": title, "sections": SECTIONS.dump_python(sections)}


def from_json(document: dict) -> tuple[str, list[Section]]:
    """Rebuild the title and sections from ``to_json`` output.

    Args:
        document: A loaded document.

    Returns:
        The title, and the top-level sections.

    Raises:
        pydantic.ValidationError: A section or block is malformed or has an unknown
            type; the message names its path ("sections.4.subsections.0.blocks.2").
    """
    return document["title"], SECTIONS.validate_python(document["sections"])
