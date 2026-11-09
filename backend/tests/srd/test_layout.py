from __future__ import annotations

import pytest

from dnd_graph_rag.srd import layout
from dnd_graph_rag.srd.layout import Line


def make_line(**overrides) -> Line:
    """A ``Line`` with plausible defaults, overridden by keyword."""
    defaults = dict(page=1, x0=57.0, y0=100.0, x1=300.0, y1=120.0,
                    baseline=112.0, column=0, text="text", markup="text",
                    max_size=10.0)
    return Line(**(defaults | overrides))


class TestLine:
    def test_given_a_heading_level_when_asked_then_the_line_is_a_heading(self):
        # Given a line the extractor gave a heading level
        line = make_line(heading_level=2)

        # When it is asked what it is
        # Then it is a heading
        assert line.is_heading is True

    def test_given_no_heading_level_when_asked_then_it_is_body_text(self):
        # Given an ordinary line
        # When it is asked what it is
        # Then it is not a heading
        assert make_line().is_heading is False


class TestTitlecase:
    def test_given_a_meaningless_casing_when_recased_then_the_words_are_titled(self):
        """The small-caps font extracts as "rEstinG"."""
        # Given a heading as the subset font extracts it
        # When it is recased
        # Then the letters, which were right, are cased sensibly
        assert layout._titlecase("rEstinG") == "Resting"

    def test_given_minor_words_when_recased_then_they_stay_lower_case(self):
        # Given a multi-word heading
        # When it is recased
        # Then the minor words are not capitalised mid-title
        assert layout._titlecase("playinG on a Grid") == "Playing on a Grid"

    def test_given_a_minor_word_first_when_recased_then_it_is_still_capitalised(self):
        # Given a heading that opens on a minor word
        # When it is recased
        # Then the first word is capitalised regardless
        assert layout._titlecase("the enVironment") == "The Environment"


class TestIsSmallCapsHeading:
    def test_given_all_bold_words_when_asked_then_it_is_a_heading(self):
        # Given a run of bold words and no digits
        spans = [{"text": "rEstinG", "font": "GillSans-Bold-SC700"}]

        # When it is classified
        # Then it is a sidebar heading
        assert layout._is_small_caps_heading("rEstinG", spans) is True

    def test_given_digits_when_asked_then_it_is_an_ability_grid(self):
        # Given text carrying numbers
        spans = [{"text": "Str 14 +2 +2", "font": "GillSans-Bold-SC700"}]

        # When it is classified
        # Then it is not a heading
        assert layout._is_small_caps_heading("Str 14 +2 +2", spans) is False

    def test_given_a_plain_span_among_them_when_asked_then_it_is_not_a_heading(self):
        # Given a run that is not entirely bold
        spans = [{"text": "rEstinG", "font": "GillSans-Bold-SC700"},
                 {"text": "and more", "font": "GillSans"}]

        # When it is classified
        # Then it is not a heading
        assert layout._is_small_caps_heading("rEstinG and more", spans) is False

    def test_given_a_whole_sentence_when_asked_then_it_is_too_long_to_be_one(self):
        # Given nine words of bold text
        text = " ".join(["word"] * 10)
        spans = [{"text": text, "font": "GillSans-Bold"}]

        # When it is classified
        # Then a heading that long is not a heading
        assert layout._is_small_caps_heading(text, spans) is False


class TestSpanMarkup:
    def test_given_a_bold_font_when_wrapped_then_the_span_is_bold(self):
        # Given a bold span
        # When it is wrapped
        # Then it carries markdown's bold markers
        assert layout._span_markup("Bite", "GillSans-Bold") == "**Bite**"

    def test_given_an_italic_font_when_wrapped_then_the_span_is_italic(self):
        # Given an italic span
        # When it is wrapped
        # Then it carries markdown's italic marker
        assert layout._span_markup("Fireball", "Caladea-Italic") == "_Fireball_"

    def test_given_both_when_wrapped_then_the_span_carries_both(self):
        # Given a bold italic span, which is how the book names an entry
        # When it is wrapped
        # Then both markers are applied, in the order the parsers expect
        assert layout._span_markup("Bite", "GillSans-BoldItalic") == "**_Bite_**"

    def test_given_surrounding_spaces_when_wrapped_then_they_stay_outside(self):
        # Given a span padded with spaces
        # When it is wrapped
        # Then the markers hug the word and the padding survives
        assert layout._span_markup(" Bite ", "GillSans-Bold") == " **Bite** "

    def test_given_whitespace_alone_when_wrapped_then_nothing_is_marked(self):
        # Given a span of pure whitespace
        # When it is wrapped
        # Then it comes back untouched
        assert layout._span_markup("   ", "GillSans-Bold") == "   "


class TestMergeMarkup:
    def test_given_two_adjacent_bold_runs_when_merged_then_they_become_one(self):
        # Given bold emitted as two spans
        # When the markup is merged
        # Then the pair of markers between them is gone
        assert layout._merge_markup("**Fire** **Breath**") == "**Fire Breath**"

    def test_given_two_adjacent_italic_runs_when_merged_then_they_become_one(self):
        # Given italic emitted as two spans
        # When the markup is merged
        # Then it reads as one run
        assert layout._merge_markup("_Level 2_ _Abjuration_") == \
            "_Level 2 Abjuration_"


class TestDocumentGrid:
    def test_given_most_pages_agreeing_when_measured_then_that_is_the_grid(self):
        """342 of 364 pages use the standard two columns."""
        # Given the frames measured on each page, most of them agreeing
        frames = [[57.0, 310.0]] * 5 + [[57.0, 210.0, 400.0]]

        # When the document's grid is derived
        # Then the majority layout wins
        assert layout.document_grid(frames) == [57.0, 310.0]


class TestSnapToGrid:
    def test_given_every_frame_on_the_grid_when_snapped_then_the_grid_is_adopted(self):
        # Given a page where only one column was measured
        # When it is snapped
        # Then the missing column is restored from the book's own grid
        assert layout.snap_to_grid([57.0], [57.0, 310.0]) == [57.0, 310.0]

    def test_given_an_extra_frame_off_the_grid_when_snapped_then_it_is_dropped(self):
        # Given a page carrying a table's cell columns as extra frames
        # When it is snapped
        # Then only the frames the grid knows about survive
        assert layout.snap_to_grid([57.0, 180.0, 310.0],
                                   [57.0, 310.0]) == [57.0, 310.0]

    def test_given_a_genuinely_different_layout_when_snapped_then_it_is_kept(self):
        """The contents pages run three and four columns."""
        # Given a page matching at most one grid column
        measured = [57.0, 150.0, 240.0, 330.0]

        # When it is snapped against a two-column grid it does not fit
        snapped = layout.snap_to_grid(measured, [57.0, 500.0])

        # Then the page keeps what it actually measured
        assert snapped == measured


class TestColumnOf:
    def test_given_a_line_inside_one_frame_when_assigned_then_it_takes_that_column(self):
        # Given a line sitting wholly in the right-hand column
        # When it is assigned
        # Then it belongs to that frame
        assert layout._column_of(310.0, 500.0, [57.0, 310.0]) == 1

    def test_given_a_line_crossing_the_gutter_when_assigned_then_it_is_full_width(self):
        # Given a section title spanning both columns
        # When it is assigned
        # Then it is a band boundary rather than column content
        assert layout._column_of(57.0, 500.0, [57.0, 310.0]) == -1

    def test_given_a_line_starting_just_left_of_its_frame_when_assigned_then_it_still_fits(self):
        # Given a line beginning a few points left of the measured frame
        # When it is assigned
        # Then the same slack that matches a page to the grid applies here
        assert layout._column_of(305.0, 500.0, [57.0, 310.0]) == 1


class TestBox:
    def test_given_a_line_when_boxed_then_the_height_comes_from_the_type_size(self):
        """PyMuPDF reports 95 of 107 lines on a typical page as 56pt tall."""
        # Given a line whose reported bbox is far taller than its type
        line = make_line(y0=60.0, y1=116.0, baseline=112.0, max_size=10.0)

        # When it is boxed
        box = layout.box(line)

        # Then the height is the type's, not the bbox's
        assert box["y0"] == pytest.approx(104.0)
        assert box["y1"] == pytest.approx(114.4)
        assert box["y1"] - box["y0"] < 30

    def test_given_a_line_when_boxed_then_the_horizontal_extent_is_trusted(self):
        # Given a line's measured left and right edges
        line = make_line(x0=57.4, x1=299.61)

        # When it is boxed
        box = layout.box(line)

        # Then they are carried through, since column detection relies on them
        assert (box["x0"], box["x1"]) == (57.4, 299.6)

    def test_given_a_line_when_boxed_then_it_names_its_own_page(self):
        # Given a line on page 186
        # When it is boxed
        # Then the box says which page to draw it on
        assert layout.box(make_line(page=186))["page"] == 186


class TestReflow:
    def test_given_two_lines_when_joined_then_a_space_separates_them(self):
        # Given a paragraph broken across two lines
        # When they are reflowed
        # Then they read as one sentence
        assert layout.reflow(["The creature", "moves 30 feet."]) == \
            "The creature moves 30 feet."

    def test_given_a_word_split_by_a_hyphen_when_joined_then_it_is_healed(self):
        # Given a word hyphenated across the break
        # When the lines are reflowed
        # Then the hyphen is gone and the halves are glued
        assert layout.reflow(["Athlet-", "ics"]) == "Athletics"

    def test_given_an_emphasis_run_broken_across_lines_when_joined_then_it_stays_one_run(self):
        """
        Two-line spell subtitles close and reopen their italic run at the
        break.
        """
        # Given a subtitle wrapped mid-run
        chunk = ["_Level 2 Abjuration (Bard, Cleric,_", "_Ranger)_"]

        # When the lines are reflowed
        joined = layout.reflow(chunk)

        # Then it is one italic run again
        assert joined == "_Level 2 Abjuration (Bard, Cleric, Ranger)_"

    def test_given_a_hyphen_inside_an_emphasis_run_when_joined_then_both_are_mended(self):
        # Given an emphasised word hyphenated across the break
        # When the lines are reflowed
        # Then the word is whole and still one emphasised token
        assert layout.reflow(["**Athlet-**", "**ics**"]) == "**Athletics**"

    def test_given_blank_lines_when_joined_then_they_contribute_nothing(self):
        # Given a chunk padded with empty lines
        # When it is reflowed
        # Then only the words survive
        assert layout.reflow(["", "The creature", "  ", "moves."]) == \
            "The creature moves."

    def test_given_two_genuinely_separate_runs_when_joined_then_they_stay_separate(self):
        # Given one line already carrying two adjacent runs
        # When it is reflowed with another
        joined = layout.reflow(["**Bite** and", "**Claw**"])

        # Then nothing on the inside of a line was spliced
        assert joined == "**Bite** and **Claw**"


class TestNormalizeWs:
    def test_given_runs_of_spaces_and_tabs_when_normalised_then_one_space_remains(self):
        # Given a cell padded by the extractor
        # When it is normalised
        # Then it is a single-spaced, trimmed string
        assert layout._normalize_ws("  Simple \t\t Melee  ") == "Simple Melee"


def make_table(**overrides) -> Line:
    """A table anchor: a ``Line`` carrying one row."""
    return make_line(**({"text": "", "markup": "", "max_size": 9.2,
                         "rows": [make_line(text="row", max_size=9.2)]}
                        | overrides))


def heading(text: str, level: int, **overrides) -> Line:
    return make_line(**({"text": text, "markup": text, "heading_level": level,
                         "max_size": 10.5} | overrides))


def prose(text: str, **overrides) -> Line:
    return make_line(**({"text": text, "markup": text} | overrides))


class TestAbsorbHeaderRows:
    def test_given_a_header_row_under_a_caption_when_absorbed_then_it_joins_the_table(self):
        """Regression: "Bard Features" lost its caption to a stray header row."""
        # Given a caption, a header row in table type, then the detected table
        caption = heading("Bard Features", 5, baseline=363.0)
        header = prose("Proficiency", baseline=377.0, max_size=9.2, x0=94.0, x1=139.0)
        table = make_table(y0=393.0, x0=58.0, x1=546.0, baseline=400.0)
        free = [caption, header]

        # When header rows are absorbed
        layout._absorb_header_rows(table, free)

        # Then the header is the table's first row and the caption is next to it
        assert table.rows[0].text == "Proficiency"
        assert free == [caption]
        assert table.y0 - caption.baseline < layout.CAPTION_GAP

    def test_given_a_stat_block_when_absorbed_then_its_subtitle_stays_prose(self):
        """Regression: stat block subtitles and AC lines became table rows."""
        # Given a stat block title, its small-type subtitle, then its ability table
        title = heading("Aboleth", 3, max_size=14.8, is_statblock_name=True,
                        baseline=100.0)
        subtitle = prose("Large Aberration", baseline=112.0, max_size=9.2)
        table = make_table(y0=125.0, x0=50.0, x1=310.0, baseline=130.0)
        free = [title, subtitle]

        # When header rows are absorbed
        layout._absorb_header_rows(table, free)

        # Then nothing moves: a stat block title is no caption
        assert free == [title, subtitle]
        assert len(table.rows) == 1


class TestMarkFloats:
    def test_given_a_caption_before_a_table_when_marked_then_both_are_one_float(self):
        # Given a level-5 heading followed by a table, then prose
        caption, table = heading("Travel Terrain", 5), make_table()
        after = prose("Body text.")

        # When the page's floats are marked
        next_id = layout.mark_floats([caption, table, after], [], 0)

        # Then caption and table share an id, and the prose is not in it
        assert caption.float_id == table.float_id == 0
        assert after.float_id is None
        assert next_id == 1

    def test_given_a_stat_block_title_before_a_table_when_marked_then_it_is_no_float(self):
        # Given a stat block title directly above its ability table
        title = heading("Aboleth", 5, is_statblock_name=True)
        table = make_table()

        # When the page's floats are marked
        layout.mark_floats([title, table], [], 0)

        # Then the stat block stays where it is
        assert title.float_id is None and table.float_id is None

    def test_given_lines_inside_a_sidebar_frame_when_marked_then_they_are_one_float(self):
        # Given a sidebar frame holding a title and text, and text outside it
        title = heading("Resting", 5, baseline=50.0)
        inside = prose("Adventurers need rest.", baseline=70.0)
        outside = prose("Hit Points measure durability.", baseline=300.0)
        frame = layout.pymupdf.Rect(50, 40, 310, 200)

        # When the page's floats are marked
        layout.mark_floats([title, inside, outside], [frame], 0)

        # Then only the framed lines belong to the float
        assert title.float_id == inside.float_id == 0
        assert outside.float_id is None

    def test_given_an_untitled_frame_after_a_sidebar_when_marked_then_it_continues_it(self):
        """A sidebar can run from one column into the next."""
        # Given a titled frame in one column and an untitled one in the next
        first = [heading("Exceptions", 5, baseline=50.0), prose("a", baseline=70.0)]
        second = [prose("b", baseline=70.0, x0=320.0, x1=540.0)]
        frames = [layout.pymupdf.Rect(50, 40, 300, 200),
                  layout.pymupdf.Rect(310, 40, 550, 200)]

        # When the page's floats are marked
        layout.mark_floats(first + second, frames, 0)

        # Then both frames are one float
        assert {l.float_id for l in first + second} == {0}


class TestJoinContinuedTables:
    def test_given_a_footnote_under_a_float_when_joined_then_it_belongs_to_it(self):
        # Given a float's table, its footnote in table type, then body text
        table = make_table(float_id=0)
        note = prose("*Appropriate equipment is needed.", max_size=9.2)
        body = prose("Body text.")

        # When continuations are joined
        layout._join_continued_tables([table, note, body])

        # Then the footnote is the table's and the body text is not
        assert note.float_id == 0
        assert body.float_id is None

    def test_given_an_uncaptioned_table_after_a_float_when_joined_then_it_belongs_to_it(self):
        """Regression: "Level 2 Bard Spells" left its p34 half behind."""
        # Given a float's table, a stray row fragment, an uncaptioned table, then prose
        first = make_table(float_id=3)
        fragment = prose("twice, rerolling any 8.", max_size=9.2)
        rest = make_table(page=2)
        body = prose("Body text.")

        # When continuations are joined
        layout._join_continued_tables([first, fragment, rest, body])

        # Then the fragment and the rest join the float, the prose does not
        assert fragment.float_id == rest.float_id == 3
        assert body.float_id is None


class TestMentions:
    def test_given_prose_naming_the_table_when_asked_then_it_mentions_it(self):
        # Given prose that wraps the table's name over a line break
        body = "as shown in the Apparatus of the Crab  Levers table."

        # When it is asked about the caption
        # Then it refers to that table
        assert layout._mentions(body, "Apparatus of the Crab Levers")

    def test_given_a_priced_caption_when_asked_then_the_price_is_ignored(self):
        # Given a caption with a parenthetical and prose naming the table
        # When it is asked
        # Then the parenthetical does not have to appear
        assert layout._mentions("see the Trinkets table", "Trinkets (Varies)")

    def test_given_the_name_without_the_word_table_when_asked_then_it_does_not(self):
        # Given prose that names the subject but not the table
        # When it is asked
        # Then it is not a reference to the table
        assert not layout._mentions("Weapons are listed below.", "Weapons")


class TestPlaceFloats:
    def test_given_a_table_mid_feature_when_placed_then_the_prose_closes_up(self):
        """Regression: Rage's rules were the content of "Barbarian Features"."""
        # Given a features section naming the table, a feature, and the table
        # printed between the feature's two paragraphs
        lines = [
            heading("Barbarian Class Features", 3),
            prose("These are listed in the Barbarian Features table."),
            heading("Level 1: Rage", 4),
            prose("You can enter a Rage."),
            heading("Barbarian Features", 5, float_id=0),
            make_table(float_id=0),
            prose("The Rage lasts 10 minutes."),
            heading("Level 1: Unarmored Defense", 4),
        ]

        # When floats are placed
        placed = layout.place_floats(lines)

        # Then the table is the first child of the section naming it, at its
        # children's level, and Rage's two paragraphs are adjacent again
        texts = [l.text for l in placed]
        assert texts.index("Barbarian Features") < texts.index("Level 1: Rage")
        assert placed[texts.index("Barbarian Features")].heading_level == 4
        rage = texts.index("Level 1: Rage")
        assert texts[rage + 1:rage + 3] == ["You can enter a Rage.",
                                            "The Rage lasts 10 minutes."]

    def test_given_a_table_at_the_end_of_its_owner_when_placed_then_it_stays(self):
        # Given a table already after the last of its owner's subsections
        lines = [
            heading("Weapons", 2),
            prose("The Weapons table lists them."),
            heading("Vex", 4),
            prose("Advantage on your next attack."),
            heading("Weapons", 5, float_id=0),
            make_table(float_id=0),
            heading("Armor", 2),
        ]

        # When floats are placed
        placed = layout.place_floats(lines)

        # Then it stays where it was, now a child of Weapons rather than Vex
        assert placed == lines
        assert lines[4].heading_level == 4

    def test_given_an_untitled_sidebar_when_placed_then_it_follows_the_owners_prose(self):
        # Given an untitled sidebar part printed before the owner's last paragraph
        lines = [
            heading("Creating Your Character", 3),
            prose("First paragraph."),
            prose("Sidebar text.", float_id=0),
            prose("Second paragraph."),
            heading("Step 1", 4),
        ]

        # When floats are placed
        placed = layout.place_floats(lines)

        # Then it comes after the owner's prose, before its first subsection
        assert [l.text for l in placed] == [
            "Creating Your Character", "First paragraph.", "Second paragraph.",
            "Sidebar text.", "Step 1"]
        assert placed[3].starts_paragraph
