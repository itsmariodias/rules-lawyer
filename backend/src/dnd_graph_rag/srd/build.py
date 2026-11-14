"""The whole of stage 1: the PDF to the document, its markdown and its page anchors."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .entities.annotate import annotate
from .entities.characters import classes, feats, origins
from .entities.creatures import check_mechanics, creatures
from .entities.equipment import equipment
from .entities.glossary import glossary
from .entity_types import type_from_records, type_sections
from .output.anchors import anchors, misplaced
from .output.document import to_json
from .output.render import render_book
from .reading.blocks import read_blocks
from .reading.pages import read_pages
from .reading.text import compounds
from .sections import build_sections, walk
from .verify import KNOWN, problems


@dataclass
class Artifact:
    """What a build produces: the document, the markdown rendered from it, its anchors, and
    every way the book disagrees with itself, ``KNOWN`` quirks among them."""

    document: dict
    markdown: str
    anchors: list[dict]
    problems: list[str]


def build(pdf: Path, markdown_name: str) -> Artifact:
    """Read the PDF into sections, records and checks.

    Args:
        pdf: The SRD PDF.
        markdown_name: The markdown's file name, recorded in ``meta``.

    Returns:
        The artifact; nothing is written.
    """
    book = read_pages(pdf)
    blocks = read_blocks([line for page in book.pages for line in page], compounds(book.pages))
    sections = build_sections(blocks)
    type_sections(sections)
    annotate(sections)
    markdown, spans, parts = render_book(book.title, sections)
    for section in walk(sections):
        section.source.char_start, section.source.char_end = spans[section.id]

    records = {"creatures": creatures(sections, pdf.name), "equipment": equipment(sections, pdf.name),
               "classes": classes(sections, pdf.name),
               "species": origins(sections, "Species Descriptions", "species", pdf.name),
               "backgrounds": origins(sections, "Background Descriptions", "background", pdf.name),
               "feats": feats(sections, pdf.name)}
    type_from_records(sections, records["classes"], records["species"] + records["backgrounds"],
                      records["feats"], records["equipment"])
    records["glossary"] = glossary(sections, pdf.name)

    page_anchors = anchors(parts)
    found = problems(blocks, sections) + misplaced(sections, page_anchors)
    meta = {"title": book.title, "pdf": pdf.name, "pages": len(book.pages), "generated": date.today().isoformat(),
            "markdown": markdown_name,
            "counts": {"sections": sum(1 for _ in walk(sections)), **{k: len(v) for k, v in records.items()},
                       "entity_types": dict(sorted(Counter(s.entity_type.value for s in walk(sections)).items()))}}
    validation = {"problems": [m for m in found if m not in KNOWN], "known_quirks": [m for m in found if m in KNOWN],
                  "stat_block_warnings": [{"creature": c["name"], "page": c["source"]["page_start"],
                                           "warnings": c["warnings"]} for c in records["creatures"] if c["warnings"]],
                  **check_mechanics(records["creatures"]), "anchor_parts": len(page_anchors)}
    return Artifact(to_json(meta, sections, records, validation), markdown, page_anchors, found)
