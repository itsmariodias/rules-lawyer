"""The document to and from JSON. The JSON is the book; markdown is rendered from it."""

from __future__ import annotations

from dnd_graph_rag.srd.model import SECTIONS, Section


def to_json(meta: dict, sections: list[Section], records: dict[str, list[dict]], validation: dict) -> dict:
    """The document as JSON-ready data.

    Args:
        meta: The book's title, the PDF, counts and the like.
        sections: The book's top-level sections.
        records: Each collection of entity records, by name ("creatures", ...).
        validation: The build's checks and what they found.

    Returns:
        ``{"meta", "sections", <each collection>, "validation"}``.
    """
    return {"meta": meta, "sections": SECTIONS.dump_python(sections), **records, "validation": validation}


def from_json(document: dict) -> tuple[str, list[Section]]:
    """The title and sections of a loaded document, as rendering needs them.

    Args:
        document: A loaded document.

    Returns:
        The title, and the top-level sections.

    Raises:
        pydantic.ValidationError: A section or block is malformed or has an unknown
            type; the message names its path ("sections.4.subsections.0.blocks.2").
    """
    return document["meta"]["title"], SECTIONS.validate_python(document["sections"])
