"""The SRD PDF to the document, its markdown and its page anchors."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dnd_graph_rag.srd.entities.annotate import annotate
from dnd_graph_rag.srd.entities.characters import classes, feats, origins
from dnd_graph_rag.srd.entities.creatures import check_mechanics, creatures
from dnd_graph_rag.srd.entities.equipment import equipment
from dnd_graph_rag.srd.entities.glossary import glossary
from dnd_graph_rag.srd.entities.references import references, unresolved
from dnd_graph_rag.srd.entity_types import type_from_records, type_sections
from dnd_graph_rag.srd.output.anchors import anchors, misplaced
from dnd_graph_rag.srd.output.document import to_json
from dnd_graph_rag.srd.output.render import render_book
from dnd_graph_rag.srd.reading.blocks import read_blocks
from dnd_graph_rag.srd.reading.pages import read_pages
from dnd_graph_rag.srd.reading.text import compounds
from dnd_graph_rag.srd.sections import build_sections, walk
from dnd_graph_rag.srd.verify import KNOWN, problems


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
    records["references"] = references(sections)

    page_anchors = anchors(parts)
    dangling = unresolved(records["references"], sections, records["glossary"])
    found = (problems(blocks, sections) + misplaced(sections, page_anchors)
             + [f"References: {target} names nothing extracted" for target in dangling])
    meta = {"title": book.title, "pdf": pdf.name, "pages": len(book.pages), "generated": date.today().isoformat(),
            "markdown": markdown_name,
            "counts": {"sections": sum(1 for _ in walk(sections)), **{k: len(v) for k, v in records.items()},
                       "entity_types": dict(sorted(Counter(s.entity_type.value for s in walk(sections)).items()))}}
    validation = {"problems": [m for m in found if m not in KNOWN], "known_quirks": [m for m in found if m in KNOWN],
                  "stat_block_warnings": [{"creature": c["name"], "page": c["source"]["page_start"],
                                           "warnings": c["warnings"]} for c in records["creatures"] if c["warnings"]],
                  **check_mechanics(records["creatures"]),
                  "unresolved_references": dangling,
                  "anchor_parts": len(page_anchors)}
    return Artifact(to_json(meta, sections, records, validation), markdown, page_anchors, found)
