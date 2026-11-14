"""Blocks to and from JSON. The JSON is the book; markdown is rendered from it."""

from __future__ import annotations

from .model import (Block, Contents, Entry, Field, Heading, ListBlock, Paragraph, Run, Section,
                    Sidebar, StatBlock, Table)


def to_json(title: str, blocks: list[Block]) -> dict:
    """The document as JSON-ready data.

    Args:
        title: The book's title, from its footers.
        blocks: The book's blocks in reading order, each naming its pages.

    Returns:
        ``{"title", "blocks"}``.
    """
    return {"title": title, "blocks": [block_json(b) for b in blocks]}


def from_json(document: dict) -> tuple[str, list[Block]]:
    """Rebuild the title and blocks from ``to_json`` output.

    Args:
        document: A loaded document.

    Returns:
        The title, and the blocks in reading order.

    Raises:
        ValueError: A block has an unknown type.
    """
    return document["title"], [block_of(b) for b in document["blocks"]]


def block_json(block: Block) -> dict:
    """One block as JSON-ready data."""
    match block:
        case Heading():
            return {"type": "heading", "level": block.level, "text": block.text, "page": block.page}
        case Paragraph():
            data = {"type": "paragraph", "pages": block.pages, "runs": runs_json(block.runs)}
            if block.role:
                data["role"] = block.role
            return data
        case Contents():
            return {"type": "contents", "pages": block.pages,
                    "entries": [{"runs": runs_json(e.runs), "page": e.page, "level": e.level}
                                for e in block.entries]}
        case ListBlock():
            data = {"type": "list", "ordered": block.ordered, "pages": block.pages,
                    "items": [[block_json(b) for b in item] for item in block.items]}
            if block.ordered:
                data["start"] = block.start
            return data
        case Sidebar():
            return {"type": "sidebar", "pages": block.pages, "title": runs_json(block.title),
                    "blocks": [block_json(b) for b in block.blocks]}
        case Table():
            return {"type": "table", "pages": block.pages, "caption": runs_json(block.caption),
                    "header": [[runs_json(c) for c in row] for row in block.header],
                    "rows": [[runs_json(c) for c in row] for row in block.rows]}
        case StatBlock():
            return {"type": "statblock", "pages": block.pages, "name": block.name,
                    "subtitle": runs_json(block.subtitle),
                    "fields": [{"label": f.label, "value": runs_json(f.value)} for f in block.fields],
                    "abilities": block.abilities,
                    "sections": [{"title": s.title, "entries": [block_json(e) for e in s.entries]}
                                 for s in block.sections]}


def block_of(data: dict) -> Block:
    """One block from JSON data."""
    match data["type"]:
        case "heading":
            return Heading(data["level"], data["text"], data["page"])
        case "paragraph":
            return Paragraph(runs_of_json(data["runs"]), data["pages"], data.get("role"))
        case "contents":
            return Contents([Entry(runs_of_json(e["runs"]), e["page"], e["level"])
                             for e in data["entries"]], data["pages"])
        case "list":
            return ListBlock(data["ordered"], [[block_of(b) for b in item] for item in data["items"]],
                             data["pages"], data.get("start", 1))
        case "sidebar":
            return Sidebar(runs_of_json(data["title"]), [block_of(b) for b in data["blocks"]],
                           data["pages"])
        case "table":
            return Table(runs_of_json(data["caption"]),
                         [[runs_of_json(c) for c in row] for row in data["header"]],
                         [[runs_of_json(c) for c in row] for row in data["rows"]], data["pages"])
        case "statblock":
            return StatBlock(data["name"], runs_of_json(data["subtitle"]),
                             [Field(f["label"], runs_of_json(f["value"])) for f in data["fields"]],
                             data["abilities"],
                             [Section(s["title"], [block_of(e) for e in s["entries"]])
                              for s in data["sections"]], data["pages"])
    raise ValueError(f"unknown block type {data['type']!r}")


def runs_json(runs: list[Run]) -> list[str | dict]:
    """Runs as JSON-ready data."""
    return [run_json(r) for r in runs]


def runs_of_json(data: list[str | dict]) -> list[Run]:
    """Runs from JSON data."""
    return [run_of(r) for r in data]


def run_json(run: Run) -> str | dict:
    """A plain run as its text; a styled run as an object naming its styles."""
    if not (run.bold or run.italic):
        return run.text
    data: dict = {"text": run.text}
    if run.bold:
        data["bold"] = True
    if run.italic:
        data["italic"] = True
    return data


def run_of(data: str | dict) -> Run:
    """One run from JSON data."""
    if isinstance(data, str):
        return Run(data)
    return Run(data["text"], data.get("bold", False), data.get("italic", False))
