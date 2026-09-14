"""
Keep GRAPH.md — and the graph explorer's palette — honest.

Neither is code, and both go stale the moment the mapper gains or loses a
label.  They are checked against ``mapping`` rather than against a live
database, so they run without Docker: the mapper is what decides the graph's
shape anyway.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dnd_graph_rag.graph import mapping

ROOT = Path(__file__).resolve().parents[2]
GRAPH_MD = ROOT / "GRAPH.md"
PALETTE = ROOT / "frontend" / "src" / "components" / "graph-layout.ts"


@pytest.fixture(scope="module")
def documented() -> tuple[set[str], set[str]]:
    """The labels and relationship types GRAPH.md has an entry for."""
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
    """The labels ``graph-layout``'s ``KINDS`` table gives a colour to."""
    if not PALETTE.exists():
        pytest.skip(f"{PALETTE} is missing")
    text = PALETTE.read_text(encoding="utf-8")
    table = re.search(r"KINDS: \[string, string\[\]\]\[\] = \[.*?\n\]", text, re.S)
    assert table, "graph-layout.ts no longer has a KINDS table to read"
    quoted = re.findall(r"'([\w]+)'", table.group(0))
    # A row is `['kind', ['Label', …]]`, so the kind name is the quoted
    # string followed by a comma and the opening of the label list — which
    # is what tells it apart from the first label inside that list.
    kinds = set(re.findall(r"\[\s*'([\w]+)'\s*,\s*\[", table.group(0)))
    return set(quoted) - kinds


@pytest.fixture(scope="module")
def built(document) -> mapping.GraphData:
    return mapping.build(document)


@pytest.fixture(scope="module")
def built_labels(built) -> set[str]:
    return {label for batch in built.nodes for label in batch.labels}


class TestGraphMd:
    """The document describing every label and relationship the loader builds."""

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
    """
    The explorer's colours, which are a priority list rather than a lookup.

    A label missing from it is not an error anywhere: the node draws, and
    only someone who knows the graph notices it is the wrong colour.  So the
    table is read out of ``graph-layout.ts`` and held against the mapper.
    """

    def test_given_the_mapper_when_compared_then_every_label_has_a_colour(
            self, built_labels, coloured):
        # Given the labels the mapper builds
        # When they are held against the palette
        # ``:Section`` is the fallback itself — it is on 2368 nodes and says
        # nothing about which one this is.
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


class TestTheArtifactsOwnClaims:
    """The assertion ``srd-parse`` makes, held against the artifact on disk."""

    def test_given_the_artifact_when_checked_then_every_section_has_geometry(
            self, document, anchors):
        """
        Character offsets and page rectangles are derived by different routes
        — one from the ``<!-- PAGE:n -->`` markers, the other from the lines
        themselves — so agreeing means both describe the same passage.
        """
        # Given the artifact and the anchors beside it
        from dnd_graph_rag.srd.pipeline import section_boxes, walk

        # When each section's range is resolved to rectangles
        for node in walk(document["sections"]):
            source = node["source"]
            boxes = section_boxes(anchors, source["char_start"],
                                  source["char_end"])

            # Then it has geometry, and that geometry is on the pages it claims
            assert boxes, f"{node['id']} has no geometry"
            pages = {box["page"] for box in boxes}
            assert min(pages) >= source["page_start"]
            assert max(pages) <= source["page_end"]
