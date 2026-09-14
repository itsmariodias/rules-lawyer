"""
A citation resolved to the book's own words, and to its place on the page.

This is the payoff of carrying ``char_start``/``char_end`` on every node:
``/source`` slices the markdown at those offsets, and the anchors map the same
range to the rectangles the UI draws over a render of the page.
"""

from __future__ import annotations

import pytest

from dnd_graph_rag.chat import source


class TestExcerpt:
    """The source text of one section, with the graph's own view of it."""

    def test_given_a_citation_when_excerpted_then_it_resolves_to_the_markdown(
            self, graph, document):
        # Given a cited section
        # When it is excerpted with no context
        excerpt = source.excerpt("11.2.114", context=0)

        # Then the book's own words come back under the right heading
        assert excerpt is not None
        assert excerpt["heading"] == "Prone [Condition]"
        assert "Prone" in excerpt["text"]

    def test_given_no_context_when_excerpted_then_the_highlight_covers_all_of_it(
            self, graph):
        # Given a citation excerpted tightly
        excerpt = source.excerpt("11.2.114", context=0)

        # When the highlight is read
        # Then the slice is exactly the section, so all of it is the citation
        assert excerpt["highlight"]["start"] == 0
        assert excerpt["highlight"]["end"] == len(excerpt["text"])

    def test_given_context_when_excerpted_then_the_slice_widens_but_not_the_highlight(
            self, graph, document):
        """
        Which is what lets the panel show a citation in its surroundings and
        still dim everything that is not it.
        """
        # Given the same citation excerpted twice
        tight = source.excerpt("11.2.114", context=0)
        wide = source.excerpt("11.2.114", context=300)

        # When the widened slice is cut at its own highlight
        highlighted = wide["text"][wide["highlight"]["start"]:
                                   wide["highlight"]["end"]]

        # Then what is highlighted is exactly the section
        assert len(wide["text"]) > len(tight["text"])
        assert highlighted == tight["text"]

    def test_given_a_citation_when_excerpted_then_it_carries_its_page_rectangles(
            self, graph):
        # Given a cited section
        excerpt = source.excerpt("11.2.114")

        # When the geometry is read
        # Then it names the page, and each box is a line rather than a block
        assert excerpt["pages"] == [186]
        assert len(excerpt["boxes"]) > 1
        for box in excerpt["boxes"]:
            assert box["page"] == 186
            # Derived from the baseline and type size, never from the reported
            # bbox, which inflates to 56pt on most lines.
            assert 0 < box["y1"] - box["y0"] < 30
            assert box["x1"] > box["x0"]

    def test_given_context_when_excerpted_then_the_boxes_mark_the_citation_only(
            self, graph):
        # Given the same citation excerpted tightly and widely
        # When the boxes are compared
        # Then they mark what was cited, not what is shown around it
        assert (source.excerpt("11.2.114", context=0)["boxes"]
                == source.excerpt("11.2.114", context=800)["boxes"])

    def test_given_a_citation_when_excerpted_then_the_reader_can_move_around_it(
            self, graph):
        # Given a cited section
        excerpt = source.excerpt("11.2.114")

        # When its surroundings are read
        # Then the parent and children come with it, as the graph knows them
        assert "parent" in excerpt and "children" in excerpt

    def test_given_an_unknown_id_when_excerpted_then_it_is_absent(self, graph):
        # Given an id no section has
        # When it is excerpted
        # Then nothing is returned, so the route can answer 404
        assert source.excerpt("999.999") is None


class TestMarkdown:
    """The intermediate markdown, read once and cached."""

    def test_given_the_artifact_when_read_then_it_is_the_same_object_each_time(
            self, markdown):
        """
        Together the two files are about 4 MB, and every citation in every
        conversation slices the same two.
        """
        # Given the markdown has been read once
        first = source.markdown()

        # When it is read again
        second = source.markdown()

        # Then the cache handed back what it read
        assert first is second


class TestAnchors:
    """Page geometry per emitted part, in document order."""

    def test_given_the_anchors_when_read_then_they_are_ordered_by_offset(
            self, anchors):
        # Given the anchors on disk
        loaded = source.anchors()

        # When their offsets are read
        starts = [anchor["start"] for anchor in loaded]

        # Then they are in document order, which is what the bisection needs
        assert starts == sorted(starts)

    def test_given_no_anchors_when_read_then_a_citation_still_resolves(
            self, settings_env, tmp_path):
        """
        Missing on an artifact generated before the anchors existed, which is
        a re-parse away rather than an error worth failing a citation over.
        """
        # Given an output directory with no anchors file in it
        settings_env(DND_GRAPH_RAG_DATA=str(tmp_path))
        source.anchors.cache_clear()

        # When the anchors are read
        loaded = source.anchors()

        # Then the caller gets no boxes rather than an error
        assert loaded == []
        source.anchors.cache_clear()
