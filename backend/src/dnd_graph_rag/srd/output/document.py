"""Blocks to and from JSON. The JSON is the book; markdown is rendered from it."""

from __future__ import annotations

from ..model import BLOCKS, Block


def to_json(title: str, blocks: list[Block]) -> dict:
    """The document as JSON-ready data.

    Args:
        title: The book's title, from its footers.
        blocks: The book's blocks in reading order, each naming its pages.

    Returns:
        ``{"title", "blocks"}``.
    """
    return {"title": title, "blocks": BLOCKS.dump_python(blocks)}


def from_json(document: dict) -> tuple[str, list[Block]]:
    """Rebuild the title and blocks from ``to_json`` output.

    Args:
        document: A loaded document.

    Returns:
        The title, and the blocks in reading order.

    Raises:
        pydantic.ValidationError: A block is malformed or has an unknown type; the
            message names its path ("blocks.4211.sections.0.entries.2").
    """
    return document["title"], BLOCKS.validate_python(document["blocks"])
