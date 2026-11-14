"""The SRD PDF to the document, its markdown and its page anchors: built, written, read back."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dnd_graph_rag.config import anchors_path_for, markdown_path_for
from dnd_graph_rag.srd.entities.annotate import annotate
from dnd_graph_rag.srd.entities.characters import classes, feats, origins
from dnd_graph_rag.srd.entities.creatures import check_mechanics, creatures
from dnd_graph_rag.srd.entities.equipment import equipment
from dnd_graph_rag.srd.entities.glossary import glossary
from dnd_graph_rag.srd.entities.references import references, unresolved
from dnd_graph_rag.srd.entity_types import type_from_records, type_sections
from dnd_graph_rag.srd.output.anchors import anchors, misplaced
from dnd_graph_rag.srd.output.document import from_json, to_json
from dnd_graph_rag.srd.output.render import render_book, section_text
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


def write(artifact: Artifact, json_path: Path) -> tuple[Path, Path, Path]:
    """Write the document, then the markdown rendered from the document as written, and the anchors.

    Args:
        artifact: From ``build``.
        json_path: Where the JSON goes; the markdown and anchors are written
            beside it (``markdown_path_for``, ``anchors_path_for``).

    Returns:
        The JSON, markdown and anchors paths.

    Raises:
        RuntimeError: The JSON read back renders other markdown than its
            character offsets were taken from.
    """
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(artifact.document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rendered, _, _ = render_book(*from_json(json.loads(json_path.read_text(encoding="utf-8"))))
    if rendered != artifact.markdown:
        raise RuntimeError("the JSON read back renders other markdown than its offsets were taken from")
    markdown_path = markdown_path_for(json_path)
    markdown_path.write_text(rendered, encoding="utf-8")
    anchors_path = anchors_path_for(markdown_path)
    anchors_path.write_text(json.dumps(artifact.anchors), encoding="utf-8")
    return json_path, markdown_path, anchors_path


def load(json_path: Path) -> dict:
    """The document as its readers use it: each section with its own text as ``content``.

    The text is rendered from the section's blocks, as the markdown is, so the
    graph, its search and its embeddings read what the markdown shows.

    Args:
        json_path: A document written by ``write``.

    Returns:
        The document, every section given ``content``.

    Raises:
        FileNotFoundError: There is no document at ``json_path``.
    """
    if not json_path.exists():
        raise FileNotFoundError(f"artifact not found: {json_path} (run `uv run dnd-graph-rag parse` first)")
    document = json.loads(json_path.read_text(encoding="utf-8"))
    texts = {section.id: section_text(section) for section in walk(from_json(document)[1])}
    stack = list(document["sections"])
    while stack:
        node = stack.pop()
        node["content"] = texts[node["id"]]
        stack.extend(node["subsections"])
    return document
