from __future__ import annotations

from rules_lawyer.srd.model import (
    Contents,
    Entry,
    Heading,
    ListBlock,
    Paragraph,
    Run,
    Sidebar,
    StatBlock,
    Table,
)
from rules_lawyer.srd.reading.blocks import read_blocks
from rules_lawyer.srd.reading.pages import Line, Span
from tests.srd.reading.helpers import MARGIN, line

HEADING = "GillSans-SemiBold"


def texts(blocks) -> list[str]:
    """The plain text of each paragraph."""
    return ["".join(r.text for r in b.runs) for b in blocks]


class TestReadBlocks:
    def test_given_a_title_and_text_when_read_then_the_title_is_a_heading(self):
        # Given a 26pt GillSans-SemiBold title above body text
        lines = [line(60, "Legal Information", font=HEADING, size=26.0), line(81, "Body.")]

        # When the page becomes blocks
        blocks = read_blocks(lines, set())

        # Then the title is a level 1 heading and the text a paragraph
        assert blocks[0] == Heading(1, "Legal Information", 1)
        assert isinstance(blocks[1], Paragraph)

    def test_given_a_heading_on_two_lines_when_read_then_it_is_one_heading(self):
        # Given "Index of Stat Blocks" printed as two 26pt lines, 31.2pt apart
        lines = [line(405.3, "Index of Stat ", font=HEADING, size=26.0),
                 line(436.5, "Blocks", font=HEADING, size=26.0)]

        # When the page becomes blocks
        # Then it is one heading
        assert read_blocks(lines, set()) == [Heading(1, "Index of Stat Blocks", 1)]

    def test_given_a_heading_in_small_caps_when_read_then_it_is_a_heading(self):
        # Given page 107's "Acid Splash": capitals 12pt, the rest 8.4pt, in the small-caps cut
        sc = "GillSans-SemiBold-SC700"
        title = Line(107, 279.1, [Span("A", sc, 12.0, 63.0, 71.0), Span("cid", sc, 8.4, 71.0, 85.0),
                                  Span(" S", sc, 12.0, 85.0, 95.0), Span("plash", sc, 8.4, 95.0, 120.0)],
                     0, MARGIN, 291.5)

        # When read
        # Then it is a level 4 heading, its text as extracted
        assert read_blocks([title], set()) == [Heading(4, "Acid Splash", 107)]

    def test_given_lines_one_step_apart_when_read_then_they_are_one_paragraph(self):
        # Given three lines at the 12pt step of 10pt text
        lines = [line(80, "One line "), line(92, "and the next "), line(104, "and the last.")]

        # When the page becomes blocks
        # Then they are one paragraph, joined with single spaces
        assert read_blocks(lines, set()) == [Paragraph([Run("One line and the next and the last.")], [1])]

    def test_given_a_paragraph_when_read_then_it_keeps_a_box_per_line(self):
        # Given two lines of 10pt text
        lines = [line(80, "One line "), line(92, "and the last.")]

        # When the page becomes blocks
        paragraph = read_blocks(lines, set())[0]

        # Then the paragraph has each line's box, for the anchors file
        assert [(box.page, box.y0, box.y1) for box in paragraph.boxes] == [(1, 72.0, 82.4), (1, 84.0, 94.4)]

    def test_given_a_wider_gap_when_read_then_a_new_paragraph_starts(self):
        # Given two lines 17.4pt apart, the gap page 1 leaves between paragraphs
        lines = [line(116.7, "First."), line(134.1, "Second.")]

        # When the page becomes blocks
        # Then each is its own paragraph
        assert texts(read_blocks(lines, set())) == ["First.", "Second."]

    def test_given_a_first_line_indent_when_read_then_a_new_paragraph_starts(self):
        # Given a line at the edge, then one indented 8pt at the usual step
        lines = [line(100, "End of one."), line(112, "Start of two", x0=71), line(124, "goes on.")]

        # When the page becomes blocks
        blocks = read_blocks(lines, set())

        # Then the indent starts a paragraph, and is not a quote
        assert texts(blocks) == ["End of one.", "Start of two goes on."]
        assert blocks[1].role is None

    def test_given_hanging_paragraphs_when_read_then_each_lead_starts_one(self):
        # Given page 9's "Weapons." and "Tools.": a bold lead at the edge, later lines 8pt in
        def lead(baseline, bold, rest):
            return Line(1, baseline, [Span(bold, "Cambria-Bold", 10.0, MARGIN, MARGIN + 40),
                                      Span(rest, "Cambria", 10.0, MARGIN + 40, MARGIN + 200)],
                        0, MARGIN, 291.5)
        lines = [lead(427.4, "Weapons.", " Anyone can wield a weapon, but profi-"),
                 line(439.4, "ciency makes you better.", x0=MARGIN + 8),
                 lead(475.4, "Tools.", " If you have proficiency with a tool, you can "),
                 line(487.4, "add your Proficiency Bonus.", x0=MARGIN + 8)]

        # When the page becomes blocks
        blocks = read_blocks(lines, set())

        # Then each lead heads one paragraph, the indented lines its own, none a quote
        assert texts(blocks) == ["Weapons. Anyone can wield a weapon, but proficiency makes you better.",
                                 ("Tools. If you have proficiency with a tool, you can add your "
                                  "Proficiency Bonus.")]
        assert [b.role for b in blocks] == [None, None]

    def test_given_one_line_paragraphs_with_leads_when_read_then_each_lead_starts_one(self):
        # Given page 13's sidebar: "Squares." on one indented line, "Speed." indented below it
        def lead(baseline, bold, rest, x0=MARGIN + 7):
            return Line(1, baseline, [Span(bold, "GillSans-BoldItalic", 9.0, x0, x0 + 40),
                                      Span(rest, "GillSans", 9.0, x0 + 40, x0 + 180)], 0, MARGIN, 291.5)
        lines = [lead(442.0, "Squares.", " Each square represents 5 feet."),
                 lead(454.0, "Speed.", " Rather than moving foot by foot, move "),
                 line(466.0, "square by square.", size=9.0)]

        # When the page becomes blocks
        # Then each lead heads its own paragraph
        assert texts(read_blocks(lines, set())) == [
            "Squares. Each square represents 5 feet.",
            "Speed. Rather than moving foot by foot, move square by square."]

    def test_given_a_lead_wrapped_onto_two_lines_when_read_then_it_is_one_paragraph(self):
        # Given page 131's "...Recharges after a Long" in bold, its lead ending "Rest)." below
        lines = [Line(1, 100, [Span("Healing Touch (Recharges after a Long ", "Cambria-BoldItalic",
                                    10.0, MARGIN, 250)], 0, MARGIN, 291.5),
                 Line(1, 112, [Span("Rest).", "Cambria-BoldItalic", 10.0, MARGIN, 90),
                               Span(" One creature regains.", "Cambria", 10.0, 90, 200)], 0, MARGIN, 291.5)]

        # When the page becomes blocks
        # Then the second line goes on with the first
        assert texts(read_blocks(lines, set())) == [
            "Healing Touch (Recharges after a Long Rest). One creature regains."]

    def test_given_every_line_indented_when_read_then_the_paragraph_is_a_quote(self):
        # Given edge text, then a block whose lines all start 8pt in
        lines = [line(100, "Include this:"), line(117.4, "Quoted", x0=71), line(129.4, "text.", x0=71)]

        # When the page becomes blocks
        blocks = read_blocks(lines, set())

        # Then the indented block is a quote
        assert blocks[1] == Paragraph([Run("Quoted text.")], [1], "quote")


class TestColumnContinuation:
    def test_given_a_column_ending_mid_sentence_when_read_then_the_paragraph_goes_on(self):
        # Given page 5: "...whether the" ends the left column, "adventurers" tops the right
        lines = [line(498.1, "(each time you sit down to play D&D), whether the "),
                 line(48.7, "adventurers are talking.", x0=313.5, column=1, left=313.5)]

        # When the page becomes blocks
        # Then the two columns hold one paragraph
        assert texts(read_blocks(lines, set())) == [
            "(each time you sit down to play D&D), whether the adventurers are talking."]

    def test_given_a_full_line_ending_a_sentence_when_read_then_the_paragraph_goes_on(self):
        # Given a column whose last line ends a sentence with no room for the next word
        full = line(700, "a line that fills its column.")
        lines = [full, line(48.7, "Next sentence.", x0=313.5, column=1, left=313.5)]
        full.right = full.x1 + 2

        # When the page becomes blocks
        # Then the paragraph went on: the next word would not have fitted
        assert len(read_blocks(lines, set())) == 1

    def test_given_a_page_ending_mid_sentence_when_read_then_the_paragraph_goes_on(self):
        # Given page 7's last line "...special abilities and actions. The" and page 8's first
        lines = [line(700, "through special abilities and actions. The", column=1, left=313.5,
                      x0=313.5),
                 line(48.7, "GM can also decide.", page=2)]

        # When the book becomes blocks
        blocks = read_blocks(lines, set())

        # Then one paragraph holds both, printed on both pages
        assert texts(blocks) == ["through special abilities and actions. The GM can also decide."]
        assert blocks[0].pages == [1, 2]

    def test_given_a_short_line_ending_a_sentence_when_read_then_a_new_paragraph_starts(self):
        # Given a column ending on a short sentence, room to spare
        lines = [line(700, "Done."), line(48.7, "New paragraph.", x0=313.5, column=1, left=313.5)]

        # When the page becomes blocks
        # Then the next column starts a new paragraph
        assert texts(read_blocks(lines, set())) == ["Done.", "New paragraph."]

    def test_given_a_lead_atop_the_next_column_when_read_then_a_new_paragraph_starts(self):
        # Given page 150-151: "**Range:** Touch" ends a column, "**Components:**" heads the next
        lines = [line(700, "Range:", " Touch", font="GillSans-SemiBold", size=9.5),
                 line(48.5, "Components:", " V, S", x0=313.5, column=1, left=313.5,
                      font="GillSans-SemiBold", size=9.5)]
        for l in lines:
            l.spans[1].font = "GillSans"

        # When the page becomes blocks
        # Then each field is its own paragraph
        assert len(read_blocks(lines, set())) == 2

    def test_given_a_field_wrapped_onto_a_plain_line_when_read_then_it_is_one_paragraph(self):
        # Given page 151's Components field, wrapped onto a plain line in the cell font
        lines = [line(48.5, "Components:", " V, S, M (a pinch of diamond dust worth ",
                      font="GillSans-SemiBold", size=9.5),
                 line(60.0, "25+ GP, which the spell consumes)", x0=71.5, font="GillSans", size=9.5)]
        lines[0].spans[1].font = "GillSans"

        # When the page becomes blocks
        # Then the wrapped line is the field's, not a table
        blocks = read_blocks(lines, set())
        assert [type(b).__name__ for b in blocks] == ["Paragraph"]


class TestFloats:
    def test_given_a_sidebar_mid_paragraph_when_read_then_it_follows_the_paragraph(self):
        # Given page 5's shape: text, a framed sidebar, the text going on in column 2
        lines = [line(498.1, "the pattern holds, whether the "),
                 line(528.6, "Round Down", font="GillSans-Bold-SC700", size=11.0, x0=72.2, left=72.2,
                      frame=0),
                 line(542.4, "Whenever you divide.", font="GillSans", size=9.0, x0=72.2, left=72.2,
                      frame=0),
                 line(48.7, "adventurers talk.", x0=313.5, column=1, left=313.5)]

        # When the page becomes blocks
        blocks = read_blocks(lines, set())

        # Then the paragraph is whole and the sidebar comes after it
        assert texts(blocks[:1]) == ["the pattern holds, whether the adventurers talk."]
        assert blocks[1] == Sidebar([Run("Round Down", bold=True)],
                                    [Paragraph([Run("Whenever you divide.")], [1])], [1])

    def test_given_a_level_five_heading_over_a_table_when_read_then_it_is_the_caption(self):
        # Given "Ability Descriptions" above a header row and one row
        lines = [line(171.2, "Ability Descriptions", font=HEADING, size=10.5),
                 Line(1, 186.0, [Span("Ability", "GillSans-SemiBold", 9.2, 317.5, 345),
                                 Span("Score Measures", "GillSans-SemiBold", 9.2, 380.1, 457)]),
                 Line(1, 200.8, [Span("Strength", "GillSans", 9.5, 317.1, 351),
                                 Span("Physical might", "GillSans", 9.5, 379.7, 434)])]

        # When the page becomes blocks
        blocks = read_blocks(lines, set())

        # Then there is one table, captioned, and no heading
        assert len(blocks) == 1 and isinstance(blocks[0], Table)
        assert blocks[0].caption == [Run("Ability Descriptions", bold=True)]


    def test_given_a_table_going_on_under_its_header_again_when_read_then_it_is_one_table(self):
        # Given page 9's Actions table and its rest atop page 10, header printed twice
        def row(baseline, cells, font=("GillSans", 9.5), page=1):
            return Line(page, baseline, [Span(t, font[0], font[1], x, x + 40) for x, t in cells])
        header = [(317.5, "Action"), (366.8, "Summary")]
        lines = [line(645.9, "Actions", font=HEADING, size=10.5),
                 row(660.8, header, font=("GillSans-SemiBold", 9.2)),
                 row(675.6, [(317.1, "Attack"), (366.4, "Attack with a weapon.")]),
                 row(52.0, header, font=("GillSans-SemiBold", 9.2), page=2),
                 row(66.8, [(317.1, "Dodge"), (366.4, "Attacks have Disadvantage.")], page=2)]

        # When the book becomes blocks
        blocks = read_blocks(lines, set())

        # Then there is one table on both pages, its rows in order
        assert len(blocks) == 1 and blocks[0].pages == [1, 2]
        assert [r[0][0].text for r in blocks[0].rows] == ["Attack", "Dodge"]


    def test_given_a_table_between_list_items_when_read_then_it_follows_the_list(self):
        # Given page 23: steps 1 and 2 in the left column, a table, then steps 3 on
        cell = lambda b, t: Line(1, b, [Span(t, "GillSans", 9.5, 317.1, 400)], 1, 313.0, 540.0)
        lines = [line(600, "1:\tChoose a Class."), line(612, "2:\tAdjust Hit Points."),
                 cell(257.8, "Barbarian"),
                 line(400, "3:\tRecord New Class Features.", x0=313.5, column=1, left=313.5)]

        # When the book becomes blocks
        blocks = read_blocks(lines, set())

        # Then the list holds all three steps and the table comes after it
        assert [type(b).__name__ for b in blocks] == ["ListBlock", "Table"]
        assert len(blocks[0].items) == 3


    def test_given_a_caption_on_two_lines_when_read_then_both_are_the_caption(self):
        # Given page 26's "Multiclass Spellcaster:" over "Spell Slots per Spell Level", then a table
        lines = [line(227.2, "Multiclass Spellcaster:", font=HEADING, size=10.5),
                 line(240.7, "Spell Slots per Spell Level", font=HEADING, size=10.5),
                 Line(1, 255.5, [Span("Level", "GillSans-SemiBold", 9.2, 68.4, 90)]),
                 Line(1, 270.3, [Span("1", "GillSans", 9.5, 76.6, 80)])]

        # When the page becomes blocks
        blocks = read_blocks(lines, set())

        # Then there is one table under the whole caption, and no heading
        assert len(blocks) == 1
        assert blocks[0].caption == [Run("Multiclass Spellcaster: Spell Slots per Spell Level", bold=True)]


class TestLists:
    def test_given_numbered_items_with_hanging_lines_when_read_then_they_are_one_list(self):
        # Given page 5's "1:" and "2:" items, their later lines hanging 11.5pt in
        lines = [line(156.7, "1:\tThe GM Describes.", font="Cambria-Bold"),
                 line(168.7, "tells the players.", x0=74.5),
                 line(180.7, "2:\tThe Players Describe.", font="Cambria-Bold"),
                 line(192.7, "what they do.", x0=74.5)]

        # When the page becomes blocks
        blocks = read_blocks(lines, set())

        # Then they are one ordered list of two items, markers gone
        assert blocks == [ListBlock(True, [
            [Paragraph([Run("The GM Describes.", bold=True), Run(" tells the players.")], [1])],
            [Paragraph([Run("The Players Describe.", bold=True), Run(" what they do.")], [1])]],
            [1], 1)]

    def test_given_a_line_back_at_the_edge_when_read_then_the_list_ends(self):
        # Given an item, then a paragraph at the column edge after a gap
        lines = [line(450, "•\tA bullet."), line(468, "This pattern holds.")]

        # When the page becomes blocks
        blocks = read_blocks(lines, set())

        # Then the list has one bulleted item and the paragraph follows it
        assert isinstance(blocks[0], ListBlock) and not blocks[0].ordered
        assert texts(blocks[1:]) == ["This pattern holds."]


class TestTermLists:
    def test_given_a_grid_of_names_when_read_then_it_is_a_list_read_down_each_column(self):
        # Given page 12's hazards: GillSans 10pt names in three columns, two rows
        def grid_row(baseline, names):
            return Line(1, baseline, [Span(n, "GillSans", 10.0, x, x + 40) for x, n in names],
                        0, MARGIN, 291.5)
        lines = [line(92.0, "defines the following hazards:"),
                 grid_row(110.4, [(MARGIN, "Burning"), (141, "Falling"), (218, "Suffocation")]),
                 grid_row(123.4, [(MARGIN, "Dehydration"), (141, "Malnutrition")])]

        # When the page becomes blocks
        blocks = read_blocks(lines, set())

        # Then the paragraph ends and the names are one bulleted list, column by column
        assert isinstance(blocks[1], ListBlock) and not blocks[1].ordered
        assert [item[0].runs[0].text for item in blocks[1].items] == [
            "Burning", "Dehydration", "Falling", "Malnutrition", "Suffocation"]


class TestContents:
    def test_given_entries_when_read_then_text_page_and_level_are_split_out(self):
        # Given a bold chapter entry, an entry at the edge and an indented one
        lines = [line(82.8, "Playing the Game.......5", font="Cambria-Bold", size=9.0),
                 line(93.3, "Rhythm of Play...........5", size=9.0),
                 line(103.8, "Ability Checks.......6", x0=MARGIN + 9, size=9.0)]

        # When the page becomes blocks
        # Then they are one contents block, levels 1, 2 and 3, leaders gone
        assert read_blocks(lines, set()) == [Contents([Entry([Run("Playing the Game", bold=True)], 5, 1),
                                                       Entry([Run("Rhythm of Play")], 5, 2),
                                                       Entry([Run("Ability Checks")], 6, 3)], [1])]

    def test_given_a_one_dot_leader_when_read_then_it_is_still_an_entry(self):
        # Given the entry the book prints as "Oath of Devotion.56"
        lines = [line(121.7, "Paladin Subclass: Oath of Devotion.56", x0=MARGIN + 9, size=9.0)]

        # When the page becomes blocks
        entry = read_blocks(lines, set())[0].entries[0]

        # Then the page number is 56 and the text keeps no dot
        assert (entry.runs[0].text, entry.page) == ("Paladin Subclass: Oath of Devotion", 56)

    def test_given_an_entry_wrapped_onto_a_second_line_when_read_then_it_is_one_entry(self):
        # Given "Monk Subclass: Warrior of the Open" and "Hand....52" 5pt further in
        lines = [line(79.7, "Monk Subclass: Warrior of the Open ", x0=MARGIN + 9, size=9.0),
                 line(90.2, "Hand..........52", x0=MARGIN + 14, size=9.0)]

        # When the page becomes blocks
        # Then the two lines are one entry at the first line's level
        assert read_blocks(lines, set()) == [
            Contents([Entry([Run("Monk Subclass: Warrior of the Open Hand")], 52, 3)], [1])]

    def test_given_a_decimal_ending_a_line_when_read_then_it_is_not_an_entry(self):
        # Given body text that ends in a number with a point
        lines = [line(100, "multiply the result by 1.5")]

        # When the page becomes blocks
        # Then it stays a paragraph
        assert isinstance(read_blocks(lines, set())[0], Paragraph)


class TestParagraphStarts:
    def test_given_a_lead_whose_stop_is_plain_when_read_then_it_starts_a_paragraph(self):
        # Given page 105: "**Distance.** The range..." then "**Touch**. The spell's..."
        first = line(174.7, "Distance.", " The range is expressed in feet.", left=313.5, x0=313.5)
        second = line(186.7, "Touch", ". The spell's effect originates", left=313.5, x0=313.5)
        for l in (first, second):
            l.spans[0].font = "Cambria-Bold"

        # When the column becomes blocks
        # Then each entry is a paragraph
        assert len(read_blocks([first, second], set())) == 2

    def test_given_formulas_on_successive_lines_when_read_then_each_is_a_paragraph(self):
        # Given page 23's two formulas, centred, the first wrapped
        lines = [line(48.8, "Spell save DC", " = 8 + modifier", x0=76.4),
                 line(61.8, "+ Proficiency Bonus", x0=135.1),
                 line(74.8, "Spell attack bonus", " = modifier", x0=74.4)]
        for l in (lines[0], lines[2]):
            l.spans[0].font = "GillSans-SemiBold"

        # When the column becomes blocks
        blocks = read_blocks(lines, set())

        # Then each formula is a paragraph, displayed rather than quoted
        assert texts(blocks) == ["Spell save DC = 8 + modifier + Proficiency Bonus",
                                 "Spell attack bonus = modifier"]
        assert all(b.role is None for b in blocks)

    def test_given_table_notes_when_read_then_each_marker_starts_a_paragraph(self):
        # Given page 192's two notes under Travel Terrain, 8.6pt apart
        lines = [line(700.1, "*Appropriate equipment is necessary.", font="GillSans", size=8.0),
                 line(708.7, "\u2020Characters' rate of travel varies.", font="GillSans", size=8.0)]

        # When they become blocks
        # Then each note is its own paragraph
        assert len(read_blocks(lines, set())) == 2

    def test_given_bold_terms_with_hanging_lines_when_read_then_each_term_is_a_paragraph(self):
        # Given page 254's creature types: a bold term at the edge, its wrap indented
        lines = [line(611.4, "Aberrations", " are utterly alien beings, such as abo-"),
                 line(623.4, "leths and cloakers.", x0=MARGIN + 8),
                 line(635.4, "Beasts", " are non-Humanoid natural creatures.")]
        for l in (lines[0], lines[2]):
            l.spans[0].font = "Cambria-Bold"

        # When the column becomes blocks
        # Then each type is one paragraph
        assert texts(read_blocks(lines, set())) == [
            "Aberrations are utterly alien beings, such as aboleths and cloakers.",
            "Beasts are non-Humanoid natural creatures."]

    def test_given_a_one_line_field_ending_a_column_when_read_then_its_hanging_wrap_joins(self):
        # Given page 94: "**Variants:** Bagpipes, dul-" ends a column, "cimer" hangs atop the next
        lines = [line(684.1, "Variants:", " Bagpipes, dul-", font="GillSans", size=9.5),
                 line(48.5, "cimer, flute.", x0=321.5, column=1, left=313.5, font="GillSans", size=9.5)]
        lines[0].spans[0].font = "GillSans-SemiBold"

        # When the page becomes blocks
        # Then the field is one paragraph
        assert texts(read_blocks(lines, set())) == ["Variants: Bagpipes, dulcimer, flute."]


class TestKeyList:
    def test_given_a_grid_of_abbreviations_when_read_then_it_is_a_list_down_each_half(self):
        # Given page 176's grid: two pairs on a line, one meaning wrapped
        def pair_line(baseline, *pairs):
            spans = []
            for x, label, meaning in pairs:
                spans += [Span(label, "GillSans-SemiBold", 10.0, x, x + 20),
                          Span(meaning, "GillSans", 10.0, x + 29, x + 80)]
            return Line(176, baseline, spans, 0, MARGIN, 290.0)
        lines = [pair_line(389.3, (66.6, "AC", "Armor Class"), (182.9, "NPC", "Nonplayer")),
                 Line(176, 400.0, [Span("character", "GillSans", 10.0, 211.9, 250.0)], 0, MARGIN, 290.0),
                 pair_line(402.3, (66.6, "C", "Concentration"))]

        # When it becomes blocks
        [block] = read_blocks(lines, set())

        # Then it is one list, the left half first
        assert isinstance(block, ListBlock)
        assert [texts(item) for item in block.items] == [
            ["AC Armor Class"], ["C Concentration"], ["NPC Nonplayer character"]]


def field_line(baseline: float, *texts: str) -> Line:
    """A stat block field line: Optima-Bold labels alternating with their values."""
    l = line(baseline, *texts, font="Optima-Regular", size=9.0)
    for span in l.spans[::2]:
        span.font = "Optima-Bold"
    return l


def aboleth() -> list[Line]:
    """The top of page 258's Aboleth: title, subtitle, a line of two fields, Speed, the
    scores and Skills."""
    return [line(109.9, "Aboleth", font="GillSans-SemiBold", size=14.8),
            line(124.7, "Large Aberration, Lawful Evil", font="Optima-Italic", size=9.0),
            field_line(141.1, "AC", " 17 ", "Initiative", " +7 (17)"),
            field_line(165.1, "Speed", " 10 ft."),
            line(177.0, "MOD", " SAVE", font="GillSans", size=6.0),
            Line(1, 188.8, [Span("S", "GillSans-SemiBold-SC700", 9.8, 65.7, 70.9),
                            Span("tr", "GillSans-SemiBold-SC700", 6.8, 70.7, 79.6),
                            Span("\t21 +5 +5", "GillSans", 9.8, 82.2, 112.0)], 0, MARGIN, 290.0),
            field_line(222.6, "Skills", " History +12")]


class TestStatBlocks:
    def test_given_a_stat_block_when_read_then_it_is_one_block_of_named_parts(self):
        # Given the Aboleth's top, then a section and an entry
        entry = line(293.0, "Amphibious.", " The aboleth can breathe air and water.",
                     font="Optima-Regular", size=9.5)
        entry.spans[0].font = "Optima-BoldItalic"
        lines = aboleth() + [line(278.8, "Traits", font="GillSans", size=12.0), entry]

        # When they become blocks
        [block] = read_blocks(lines, set())

        # Then one stat block holds them, each part by name
        assert isinstance(block, StatBlock)
        assert (block.name, block.subtitle) == ("Aboleth", [Run("Large Aberration, Lawful Evil", italic=True)])
        assert [(f.label, f.value) for f in block.fields] == [
            ("AC", [Run("17")]), ("Initiative", [Run("+7 (17)")]), ("Speed", [Run("10 ft.")]),
            ("Skills", [Run("History +12")])]
        assert block.abilities == [["Str", "21", "+5", "+5"]]
        assert [s.title for s in block.sections] == ["Traits"]
        assert texts(block.sections[0].entries) == ["Amphibious. The aboleth can breathe air and water."]

    def test_given_text_after_a_stat_block_when_read_then_the_stat_block_ends(self):
        # Given the Aboleth's top, then text in the body type
        lines = aboleth() + [line(300, "The aboleth lairs underwater.")]

        # When they become blocks
        # Then the text is a paragraph after the stat block
        assert [type(b).__name__ for b in read_blocks(lines, set())] == ["StatBlock", "Paragraph"]
