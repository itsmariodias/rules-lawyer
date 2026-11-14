from __future__ import annotations

from dnd_graph_rag.srd.model import Run, plain
from dnd_graph_rag.srd.reading.pages import Line, Span
from dnd_graph_rag.srd.reading.text import compounds, runs_of, style

from .helpers import line


class TestRunsOf:
    def test_given_a_syllable_break_when_joined_then_the_hyphen_goes(self):
        # Given "contra-" ending a line and "dict" starting the next
        lines = [line(100, "sometimes contra-"), line(112, "dict a rule")]

        # When "contra-dict" is printed nowhere with its hyphen
        runs = runs_of(lines, set())

        # Then the word is whole again
        assert runs == [Run("sometimes contradict a rule")]

    def test_given_a_compound_broken_at_its_hyphen_when_joined_then_the_hyphen_stays(self):
        # Given "10-foot-" ending a line and "wide" starting the next
        lines = [line(100, "a 10-foot-"), line(112, "wide line")]

        # When the book prints "foot-wide" within a line elsewhere
        runs = runs_of(lines, {"foot-wide"})

        # Then the hyphen stays and no space is added
        assert runs == [Run("a 10-foot-wide line")]

    def test_given_a_hyphen_before_a_capital_when_joined_then_it_stays(self):
        # Given page 15's cover cell "Three-" over "Quarters"
        # When joined
        # Then the hyphen is the word's own and no space is added
        assert plain(runs_of([line(100, "Three-"), line(112, "Quarters")], set())) == "Three-Quarters"

    def test_given_a_url_broken_after_a_slash_when_joined_then_no_space_is_added(self):
        # Given the license URL split after "4.0/"
        lines = [line(158, "at https://creativecommons.org/licenses/by/4.0/"), line(170, "legalcode.")]

        # When joined
        # Then the URL is whole
        assert plain(runs_of(lines, set())) == "at https://creativecommons.org/licenses/by/4.0/legalcode."

    def test_given_a_line_ending_in_a_dash_when_joined_then_no_space_is_added(self):
        # Given page 13's "whether creatures or objects" and a dash ending a line
        lines = [line(670, "things\u2014whether creatures or objects\u2014"), line(682, "count squares")]

        # When joined
        # Then the dash stays closed up, as the book prints it mid-line
        assert plain(runs_of(lines, set())) == "things\u2014whether creatures or objects\u2014count squares"

    def test_given_mixed_fonts_when_joined_then_runs_follow_the_style(self):
        # Given a line with an italic span between plain ones
        lines = [Line(1, 100, [Span("Cast ", "Cambria", 10, 63, 90),
                               Span("Fireball", "Cambria-Italic", 10, 90, 130),
                               Span(" now.", "Cambria", 10, 130, 150)])]

        # When joined
        # Then the italic span is its own run
        assert runs_of(lines, set()) == [Run("Cast "), Run("Fireball", italic=True), Run(" now.")]

    def test_given_a_space_at_a_bold_runs_edge_when_joined_then_it_moves_to_the_plain_run(self):
        # Given a bold lead ending its line, the plain text on the next line
        lines = [line(100, "The GM Describes.", font="Cambria-Bold"), line(112, "tells the players.")]

        # When joined
        # Then the joining space is plain, so the bold run is the words alone
        assert runs_of(lines, set()) == [Run("The GM Describes.", bold=True), Run(" tells the players.")]

    def test_given_spans_a_word_space_apart_when_joined_then_a_space_separates_them(self):
        # Given page 13's small-caps title: "on" and "a" printed 3.5pt apart, no space character
        title = Line(13, 404.2, [Span("P", "GillSans-Bold-SC700", 11.0, 322.7, 330.4),
                                 Span("laying", "GillSans-Bold-SC700", 8.0, 330.4, 363.7),
                                 Span("on", "GillSans-Bold-SC700", 8.0, 367.2, 380.9),
                                 Span("a", "GillSans-Bold-SC700", 8.0, 384.3, 390.8),
                                 Span(" G", "GillSans-Bold-SC700", 11.0, 390.9, 403.0),
                                 Span("rid", "GillSans-Bold-SC700", 8.0, 403.2, 418.4)])

        # When joined
        # Then the gaps are spaces, and letters 0.0pt apart stay one word
        assert plain(runs_of([title], set())) == "Playing on a Grid"

    def test_given_punctuation_alone_in_a_style_when_joined_then_it_is_plain(self):
        # Given page 24's plain "section" and an italic period after it
        lines = [Line(24, 100, [Span("the section", "Cambria", 10, 63, 110),
                                Span(".", "Cambria-Italic", 10, 110, 112),
                                Span(" You begin", "Cambria", 10, 112, 150)])]

        # When joined
        # Then it is one plain run, so nothing renders as "_._"
        assert runs_of(lines, set()) == [Run("the section. You begin")]

    def test_given_tabs_and_double_spaces_when_joined_then_they_are_single_spaces(self):
        # Given a list marker's tab and a double space
        # When joined
        # Then whitespace is one space
        assert plain(runs_of([line(100, "1:\tThe  GM")], set())) == "1: The GM"


    def test_given_a_control_character_when_joined_then_it_is_dropped(self):
        # Given page 19's "1:", a tab, then a BEL before "Choose a Class."
        # When joined
        # Then only printing text is left
        assert plain(runs_of([line(100, "1:\t\x07Choose a Class.")], set())) == "1: Choose a Class."


    def test_given_a_hyphen_marked_by_a_zero_width_space_when_joined_then_it_stays(self):
        # Given page 254's "real-" and a zero-width space ending a line
        lines = [line(100, "or real-\u200b"), line(112, "world folklore")]

        # When joined, "real-world" printed nowhere else
        # Then the hyphen is the word's own, and the invisible space is gone
        assert plain(runs_of(lines, set())) == "or real-world folklore"

    def test_given_a_soft_hyphen_at_a_line_end_when_joined_then_the_word_is_whole(self):
        # Given page 66's "Meta" + soft hyphen ending a line, "magic" starting the next,
        # and page 24's soft hyphen inside "spell-casters"
        lines = [line(100, "your Meta\u00ad"), line(112, "magic options for spell\u00adcasters")]

        # When joined
        # Then soft hyphens vanish and the broken word closes up
        assert runs_of(lines, set()) == [Run("your Metamagic options for spellcasters")]

    def test_given_a_hyphen_beside_a_number_at_a_line_end_when_joined_then_it_stays(self):
        # Given page 98's "15-" / "foot" and page 173's "10-by-" / "10-foot"
        # When joined
        # Then each hyphen stays and no space is added
        assert runs_of([line(100, "a 15-"), line(112, "foot radius")], set()) == [Run("a 15-foot radius")]
        assert runs_of([line(100, "ten 10-by-"), line(112, "10-foot panels")], set()) == [
            Run("ten 10-by-10-foot panels")]

    def test_given_a_style_ending_inside_a_word_when_read_then_it_takes_the_whole_word(self):
        # Given page 40's Life Domain Spells: "Cure Wound" italic, then "s, " upright
        spans = [Span("Cure Wound", "GillSans-Italic", 9.5, 411.9, 458.0),
                 Span("s, ", "GillSans", 9.5, 458.1, 466.7)]

        # When its runs are read
        runs = runs_of([Line(40, 173.8, spans, 1, 313.5, 540.0)], set())

        # Then the italic covers the whole name
        assert runs == [Run("Cure Wounds", italic=True), Run(",")]


class TestCompounds:
    def test_given_lines_when_read_then_hyphenated_words_within_them_are_kept(self):
        # Given a mid-line compound and a line-end hyphen
        pages = [[line(100, "a 10-foot-wide Cone of contra-"), line(112, "diction")]]

        # When compounds are collected
        # Then only a word printed with its hyphen inside a line counts
        assert compounds(pages) == {"foot-wide"}


class TestStyle:
    def test_given_font_names_when_read_then_bold_and_italic_follow_the_suffix(self):
        # Given the book's body fonts
        # When their styles are read
        # Then the suffix decides, and a bare family is plain
        assert style(Span("", "Cambria", 10, 0, 0)) == (False, False)
        assert style(Span("", "Cambria-BoldItalic", 10, 0, 0)) == (True, True)
        assert style(Span("", "Optima-Bold", 9, 0, 0)) == (True, False)
        assert style(Span("", "Optima-Italic", 9, 0, 0)) == (False, True)
