"""
Holds GRAPH.md, ``graph-layout.ts``'s ``KINDS`` table and ``Markdown.tsx``'s
citation pattern against the backend.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dnd_graph_rag.graph import mapping

ROOT = Path(__file__).resolve().parents[2]
GRAPH_MD = ROOT / "GRAPH.md"
PALETTE = ROOT / "frontend" / "src" / "components" / "graph-layout.ts"
MARKDOWN_TSX = ROOT / "frontend" / "src" / "components" / "Markdown.tsx"


@pytest.fixture(scope="module")
def documented() -> tuple[set[str], set[str]]:
    """Labels and relationship types with an entry in GRAPH.md."""
    if not GRAPH_MD.exists():
        pytest.skip(f"{GRAPH_MD} is missing")
    text = GRAPH_MD.read_text(encoding="utf-8")
    labels = {label
              for entry in re.findall(r"^### `:([\w:]+)`", text, re.M)
              for label in entry.split(":")}
    types = set(re.findall(r"^### `([A-Z_]+)`", text, re.M))
    return labels, types


@pytest.fixture(scope="module")
def coloured() -> set[str]:
    """Labels with a colour in ``graph-layout.ts``'s ``KINDS`` table."""
    if not PALETTE.exists():
        pytest.skip(f"{PALETTE} is missing")
    text = PALETTE.read_text(encoding="utf-8")
    table = re.search(r"KINDS: \[string, string\[\]\]\[\] = \[.*?\n\]", text, re.S)
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
        stale = coloured - built_labels

        # Then the legend does not offer a kind nothing can be
        assert not stale, ("graph-layout's KINDS still colours labels nothing "
                           f"builds: {sorted(stale)}")


class TestCitationPattern:
    def test_given_the_frontend_copy_when_compared_then_it_matches_the_backend(self):
        # Given the citation pattern the frontend numbers and links
        from dnd_graph_rag.chat.retrieval import CITATION

        source = MARKDOWN_TSX.read_text(encoding="utf-8")
        found = re.search(r"const CITATION = /(.+)/g\n", source)
        assert found, "Markdown.tsx no longer defines CITATION as a regex literal"

        # When it is compared with the backend's
        # Then the two recognise exactly the same citations
        assert found.group(1) == CITATION.pattern
