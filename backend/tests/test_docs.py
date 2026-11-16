"""
Holds GRAPH.md, ``graph-layout.ts``'s ``KINDS`` table and ``Markdown.tsx``'s
citation pattern against the backend.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from rules_lawyer.chat.retrieval import neighbourhood
from rules_lawyer.graph import mapping

ROOT = Path(__file__).resolve().parents[2]
GRAPH_MD = ROOT / "GRAPH.md"
PALETTE = ROOT / "frontend" / "src" / "panel" / "graph" / "graph-layout.ts"
MARKDOWN_TSX = ROOT / "frontend" / "src" / "chat" / "Markdown.tsx"


@pytest.fixture(scope="module")
def documented() -> tuple[set[str], set[str]]:
    """Labels and relationship types with an entry in GRAPH.md."""
    if not GRAPH_MD.exists():
        pytest.skip(f"{GRAPH_MD} is missing")
    text = GRAPH_MD.read_text(encoding="utf-8")
    labels = {label
              for entry in re.findall(r"^### `:([\w:]+)`", text, re.MULTILINE)
              for label in entry.split(":")}
    types = set(re.findall(r"^### `([A-Z_]+)`", text, re.MULTILINE))
    return labels, types


@pytest.fixture(scope="module")
def coloured() -> set[str]:
    """Labels with a colour in ``graph-layout.ts``'s ``KINDS`` table."""
    if not PALETTE.exists():
        pytest.skip(f"{PALETTE} is missing")
    text = PALETTE.read_text(encoding="utf-8")
    table = re.search(r"KINDS: \[string, string\[\]\]\[\] = \[.*?\n\]", text, re.DOTALL)
    assert table, "graph-layout.ts no longer has a KINDS table to read"
    quoted = re.findall(r"'([\w]+)'", table.group(0))
    # Rows are `['kind', ['Label', …]]`; a kind is followed by `, [`.
    kinds = set(re.findall(r"\[\s*'([\w]+)'\s*,\s*\[", table.group(0)))
    return set(quoted) - kinds


@pytest.fixture(scope="module")
def built(document) -> mapping.GraphData:
    return mapping.build(document)


@pytest.fixture(scope="module")
def built_labels(built) -> set[str]:
    return {label for batch in built.nodes for label in batch.labels}


class TestGraphMd:
    def test_given_the_mapper_when_compared_then_every_label_is_documented(
            self, built_labels, documented):
        # Given the labels the mapper actually builds
        labels, _ = documented

        # When they are held against the document
        missing = built_labels - labels

        # Then nothing is built that GRAPH.md does not describe
        assert not missing, ("GRAPH.md has no entry for these labels: "
                             f"{sorted(missing)}")

    def test_given_the_mapper_when_compared_then_no_label_is_described_in_vain(
            self, built_labels, documented):
        # Given the labels GRAPH.md describes
        labels, _ = documented

        # When they are held against the mapper
        stale = labels - built_labels

        # Then the document has not outlived the code
        assert not stale, ("GRAPH.md still describes labels nothing builds: "
                           f"{sorted(stale)}")

    def test_given_the_mapper_when_compared_then_every_relationship_is_documented(
            self, built, documented):
        # Given the relationship types the mapper builds
        _, types = documented
        built_types = set(built.counts_by_type())

        # When they are held against the document
        missing = built_types - types

        # Then every edge in the graph is described
        assert not missing, ("GRAPH.md has no entry for these relationship "
                             f"types: {sorted(missing)}")

    def test_given_the_mapper_when_compared_then_no_relationship_is_described_in_vain(
            self, built, documented):
        # Given the relationship types GRAPH.md describes
        _, types = documented
        built_types = set(built.counts_by_type())

        # When they are held against the mapper
        stale = types - built_types

        # Then nothing is documented that nothing builds
        assert not stale, ("GRAPH.md still describes relationships nothing "
                           f"builds: {sorted(stale)}")


class TestGraphViewPalette:
    def test_given_the_mapper_when_compared_then_every_label_has_a_colour(
            self, built_labels, coloured):
        # Given the labels the mapper builds
        # When they are held against the palette
        # ``:Section`` is deliberately uncoloured (the grey fallback).
        missing = built_labels - coloured - {"Section"}

        # Then no node falls through to the bare-section grey by accident
        assert not missing, ("graph-layout's KINDS gives no colour to these "
                             f"labels: {sorted(missing)}")

    def test_given_the_mapper_when_compared_then_no_colour_is_kept_in_vain(
            self, built_labels, coloured):
        # Given the labels the palette colours
        # When they are held against the mapper
        # The book node is made by the graph view's walk, not the mapper.
        stale = coloured - built_labels - {neighbourhood.BOOK_LABEL}

        # Then the legend does not offer a kind nothing can be
        assert not stale, ("graph-layout's KINDS still colours labels nothing "
                           f"builds: {sorted(stale)}")


class TestCitationPattern:
    def test_given_the_frontend_copy_when_compared_then_it_matches_the_backend(self):
        # Given the citation pattern the frontend numbers and links
        from rules_lawyer.chat.retrieval.search import CITATION

        source = MARKDOWN_TSX.read_text(encoding="utf-8")
        found = re.search(r"const CITATION = /(.+)/g\n", source)
        assert found, "Markdown.tsx no longer defines CITATION as a regex literal"

        # When it is compared with the backend's
        # Then the two recognise exactly the same citations
        assert found.group(1) == CITATION.pattern


class TestTheArtifactsOwnClaims:
    def test_given_the_artifact_when_checked_then_every_section_has_geometry_on_its_pages(
            self, document, anchors):
        # Given the artifact and the anchors beside it
        from rules_lawyer.srd.output.anchors import boxes_between

        # When each section's range is resolved to rectangles
        stack = list(document["sections"])
        while stack:
            node = stack.pop()
            stack.extend(node["subsections"])
            source = node["source"]
            pages = {box["page"] for box in boxes_between(anchors, source["char_start"], source["char_end"])}

            # Then it has geometry, and that geometry is on the pages it claims
            assert pages, f"{node['id']} has no geometry"
            assert source["page_start"] <= min(pages) and max(pages) <= source["page_end"]
