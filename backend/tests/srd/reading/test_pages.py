from __future__ import annotations

from collections import Counter

import pymupdf
import pytest

from dnd_graph_rag.config import get_settings
from dnd_graph_rag.srd.reading.pages import (
    Line,
    Span,
    attach_superscripts,
    column_edges,
    column_of,
    page_lines,
    read_pages,
    shaded_halves,
    split_footer,
)


@pytest.fixture(scope="module")
def pdf():
    """The checked-in SRD, open for the module."""
    path = get_settings().pdf_path
    if not path.exists():
        pytest.skip(f"no PDF at {path}")
    with pymupdf.open(path) as doc:
        yield doc


class TestPageLines:
    def test_given_page_one_when_read_then_the_heading_comes_first(self, pdf):
        # Given the Legal Information page
        # When its lines are read
        lines = page_lines(pdf[0], 1)

        # Then the first line is the title, alone on its baseline
        assert lines[0].text == "Legal Information"
        assert lines[0].page == 1

    def test_given_page_one_when_read_then_the_footer_is_the_last_line(self, pdf):
        # Given a page with a page number and running title at its foot
        # When its lines are read
        lines = page_lines(pdf[0], 1)

        # Then both share the last line, below the body
        assert [s.text.strip() for s in lines[-1].spans] == ["1", "System Reference Document 5.2.1"]

    def test_given_spans_on_one_baseline_when_read_then_they_form_one_line(self, pdf):
        # Given a line printed as three spans (text, link-styled text, text)
        # When the page is read
        lines = page_lines(pdf[0], 1)

        # Then the spans are one line, left to right
        line = next(l for l in lines if "dndbeyond" in l.text)
        assert line.text.startswith("Coast LLC, available at https://www.dndbeyond.com/srd.")
        assert [s.x0 for s in line.spans] == sorted(s.x0 for s in line.spans)


    def test_given_the_contents_page_when_read_then_its_three_columns_are_read_in_turn(self, pdf):
        # Given page 2, three columns of contents entries side by side
        # When its lines are read
        lines = page_lines(pdf[1], 2)

        # Then each column's lines come before the next column's, and no line
        # mixes two columns
        assert sorted({(l.column, l.left) for l in lines}) == [(0, 54.0), (1, 219.0), (2, 384.0)]
        columns = [l.column for l in lines]
        assert columns == sorted(columns)
        assert lines[1].text.startswith("Legal Information")


    def test_given_a_table_across_the_gutter_when_read_then_the_columns_still_split(self, pdf):
        # Given page 9: the Skills table runs the page's width above two columns
        # When its lines are read
        lines = page_lines(pdf[8], 9)

        # Then the table does not hide the gutter: "Equipment Proficiencies"
        # heads the right column, apart from the left column's text beside it
        assert sorted({(l.column, l.left) for l in lines if l.baseline < 740}) == [(0, 63.0), (1, 313.0)]
        assert any(l.text == "Equipment Proficiencies" and l.column == 1 for l in lines)

    def test_given_a_table_shaded_across_the_gutter_when_read_then_its_rows_stay_whole(self, pdf):
        # Given page 24's Starting Equipment at Higher Levels, its Magic Items under the right column
        # When its lines are read
        lines = page_lines(pdf[23], 24)

        # Then the header is one line in the left column, all three labels on it
        header = next(l for l in lines if l.text.startswith("Starting Level"))
        assert header.column == 0
        assert [s.text for s in header.spans] == ["Starting Level", "Equipment and Money", "Magic Items"]

    def test_given_a_full_width_table_with_a_label_at_the_cell_size_when_read_then_it_stays_in_the_header(self, pdf):
        # Given page 101's Airborne and Waterborne Vehicles: "Cost" is semibold 9.5pt
        lines = page_lines(pdf[100], 101)

        # When its lines are read
        # Then "Cost" ends the header line with the other labels
        header = next(l for l in lines if l.text.startswith("Ship"))
        assert header.spans[-1].text == "Cost"

    def test_given_table_notes_across_the_gutter_when_read_then_the_columns_still_split(self, pdf):
        # Given page 192: Travel Terrain's notes, GillSans 8pt, run the page's width
        lines = page_lines(pdf[191], 192)

        # When its lines are read
        # Then the page has its two columns, "Vehicles" heading the right one
        assert any(l.text == "Vehicles" and l.column == 1 for l in lines)

    def test_given_a_caption_a_point_left_of_its_column_when_read_then_both_share_it(self, pdf):
        # Given page 217: "Deck of Illusions" at 313.4, the column's text at 314
        lines = page_lines(pdf[216], 217)

        # When its lines are read
        # Then the caption (10.5pt; the item's heading is 12pt) heads the right column
        assert next(l for l in lines if l.text == "Deck of Illusions" and l.size == 10.5).column == 1

    def test_given_page_five_when_read_then_sidebar_lines_know_their_frame(self, pdf):
        # Given page 5, with a sidebar at the foot of each column
        # When its lines are read
        lines = page_lines(pdf[4], 5)

        # Then each sidebar's lines share a frame, measured from the frame's text edge
        framed = {(l.column, l.frame, round(l.left, 1)) for l in lines if l.frame is not None}
        assert framed == {(0, 0, 72.2), (1, 1, 322.7)}
        title = next(l for l in lines if l.frame == 0)
        assert title.text == "Exceptions Supersede General Rules"


class TestColumnEdges:
    def test_given_indents_within_a_column_when_measured_then_they_fold_into_it(self):
        # Given lines starting at the edge and at 9 and 14pt indents
        starts = Counter({54.0: 20, 63.0: 30, 68.0: 3})

        # When the edges are measured
        # Then there is one column
        assert column_edges(starts, starts, []) == [54.0]

    def test_given_text_crossing_the_strip_when_measured_then_it_is_not_an_edge(self):
        # Given table cells starting at 179, with prose running across x=179
        starts = Counter({63.0: 40, 179.0: 6, 313.0: 40})
        prose = [Span("a long line of prose", "Cambria", 10.0, 63.0, 290.0)]

        # When the edges are measured
        # Then the cells are not a column, the gutter at 313 is
        assert column_edges(starts, starts, prose) == [63.0, 313.0]

    def test_given_a_column_holding_only_an_inset_table_when_measured_then_its_caption_is_the_edge(self):
        # Given page 26: prose at 63, then a caption at 313, a header at 318 and 34 rows at 325
        starts = Counter({63.0: 40, 313.0: 1, 318.0: 1, 325.0: 34})
        prose = Counter({63.0: 40, 313.0: 1})

        # When the edges are measured
        # Then the caption's start leads the table inset beside it
        assert column_edges(starts, prose, []) == [63.0, 313.0]

    def test_given_a_column_of_table_cells_beside_a_table_when_measured_then_it_is_not_an_edge(self):
        # Given page 33: a caption at 313 over a spell list whose School column starts at 439
        starts = Counter({63.0: 40, 313.0: 1, 317.0: 30, 439.0: 30, 516.0: 30})
        prose = Counter({63.0: 40, 313.0: 1})

        # When the edges are measured
        # Then the cells lead no prose, so the table is one column
        assert column_edges(starts, prose, []) == [63.0, 313.0]

    def test_given_no_line_starts_when_measured_then_there_is_one_column(self):
        # Given an empty page
        # When measured
        # Then one column covers it
        assert column_edges(Counter(), Counter(), []) == [0.0]


class TestShadedHalves:
    def test_given_one_edge_and_shaded_halves_side_by_side_when_measured_then_the_right_half_is_an_edge(self):
        # Given a page of table halves: shading from 63 to 289.6 and from 313.5 to 540.1
        shading = [pymupdf.Rect(63.0, 56.7, 289.6, 703.7), pymupdf.Rect(313.5, 56.7, 540.1, 715.0)]

        # When the edges are completed
        # Then the right half's left side is the second column
        assert shaded_halves([67.0], shading) == [67.0, 313.0]

    def test_given_two_measured_edges_when_completed_then_they_stand(self):
        # Given page 6's Ability Modifiers halves inside the left column
        shading = [pymupdf.Rect(63.0, 68, 168, 174), pymupdf.Rect(185.0, 68, 290, 174)]

        # When the edges are completed
        # Then nothing is added to a page already measured as two columns
        assert shaded_halves([63.0, 313.0], shading) == [63.0, 313.0]


class TestColumnOf:
    def test_given_edges_when_placed_then_a_span_takes_the_last_edge_left_of_it(self):
        # Given the contents page's three edges
        edges = [54.0, 219.0, 384.0]

        # When spans are placed
        # Then each belongs to the column it starts in
        assert [column_of(x, edges) for x in (24.0, 63.0, 228.0, 384.0, 500.0)] == [0, 0, 1, 2, 2]


class TestSplitFooter:
    def test_given_page_one_when_split_then_the_body_ends_and_the_title_is_read(self, pdf):
        # Given page 1's lines, footer included
        lines = page_lines(pdf[0], 1)

        # When the footer is split off
        body, title = split_footer(lines)

        # Then the body ends with the page's text and the title drops the page number
        assert body[-1].text.strip() == "to you."
        assert title == "System Reference Document 5.2.1"


class TestReadPages:
    def test_given_the_book_when_read_then_every_footer_agrees_on_the_title(self, pdf):
        # Given the whole SRD
        # When it is read
        book = read_pages(get_settings().pdf_path)

        # Then it has one title and a body for each of its 364 pages
        assert book.title == "System Reference Document 5.2.1"
        assert len(book.pages) == 364


class TestLine:
    def test_given_spans_of_two_sizes_when_measured_then_the_size_is_the_larger(self):
        # Given a line mixing 9 and 10pt type
        line = Line(1, 100.0, [Span("a ", "Cambria", 9.0, 0, 5), Span("b", "Cambria", 10.0, 5, 9)])

        # When its size and text are read
        # Then the size is the larger and the text is the spans joined
        assert line.size == 10.0
        assert line.text == "a b"
        assert line.x0 == 0

    def test_given_spans_a_word_gap_apart_when_read_then_the_text_has_a_space(self):
        # Given page 293's stat block title, "Gray" and "Ooze" with the space dropped
        line = Line(293, 307.1, [Span("Gray", "GillSans-SemiBold", 14.8, 63.0, 94.1),
                                 Span("Ooze", "GillSans-SemiBold", 14.8, 98.4, 133.1)])

        # When its text is read
        # Then the gap is a space
        assert line.text == "Gray Ooze"


class TestAttachSuperscripts:
    def test_given_a_raised_dagger_after_a_word_when_attached_then_it_joins_the_word(self):
        # Given page 192's "Special" and a 5.5pt dagger 3.2pt above its baseline
        word = Span("Special", "GillSans", 9.5, 135.4, 162.3, 683.2)
        dagger = Span("\u2020", "GillSans", 5.5, 162.3, 165.0, 680.0)

        # When superscripts are attached
        spans = attach_superscripts([word, dagger])

        # Then one span remains, the dagger at its end
        assert [(s.baseline, s.text) for s in spans] == [(683.2, "Special\u2020")]
