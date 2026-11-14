"""Extract the SRD to JSON, then render the markdown from that JSON.

Usage: ``uv run python -m dnd_graph_rag.srd``. Writes
``data/output/srd_hierarchy.json``, and ``srd_hierarchy.md`` and its page
anchors (``srd_hierarchy.anchors.json``) beside it, then
exits non-zero if the book disagrees with itself anywhere ``verify`` looks,
other than in its known quirks. Each section's character offsets come from
rendering the sections; the JSON read back must render the same markdown.
"""

from __future__ import annotations

import json
import sys

from ..config import anchors_path_for, get_settings, markdown_path_for
from .entity_types import type_sections
from .output.anchors import anchors, misplaced
from .output.document import from_json, to_json
from .output.render import render_book
from .reading.blocks import read_blocks
from .reading.pages import read_pages
from .reading.text import compounds
from .sections import build_sections, walk
from .verify import KNOWN, problems


def main() -> None:
    """Extract every page, write the JSON, render the markdown from it."""
    settings = get_settings()
    json_path = settings.output_path
    json_path.parent.mkdir(parents=True, exist_ok=True)

    book = read_pages(settings.pdf_path)
    hyphenated = compounds(book.pages)
    lines = [line for page in book.pages for line in page]
    blocks = read_blocks(lines, hyphenated)
    sections = build_sections(blocks)
    type_sections(sections)
    markdown, spans, parts = render_book(book.title, sections)
    for section in walk(sections):
        section.source.char_start, section.source.char_end = spans[section.id]
    document = to_json(book.title, sections)
    json_path.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    rendered, _, _ = render_book(*from_json(loaded))
    if rendered != markdown:
        raise RuntimeError("the JSON read back renders other markdown than its offsets were taken from")
    md_path = markdown_path_for(json_path)
    md_path.write_text(rendered, encoding="utf-8")
    page_anchors = anchors(parts)
    anchors_path = anchors_path_for(md_path)
    anchors_path.write_text(json.dumps(page_anchors), encoding="utf-8")
    print(f"{json_path}\n{md_path}\n{anchors_path}")
    found = problems(blocks, sections) + misplaced(sections, page_anchors)
    for message in found:
        print(f"known quirk: {message}" if message in KNOWN else message)
    if set(found) - KNOWN:
        sys.exit(1)
    print("The book agrees with itself, but for its known quirks.")


if __name__ == "__main__":
    main()
