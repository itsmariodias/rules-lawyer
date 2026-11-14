from __future__ import annotations

from dnd_graph_rag.srd.model import Run, Table, plain
from dnd_graph_rag.srd.reading.pages import Line, Span
from dnd_graph_rag.srd.reading.tables import (
    extend_table,
    is_table_line,
    repeat_width,
    table,
    table_end,
    table_run,
    wraps_field,
)

HEADER = ("GillSans-SemiBold", 9.2)
CELL = ("GillSans", 9.5)


def row(baseline: float, *cells: tuple[float, str], font: tuple[str, float] = CELL) -> Line:
    """A table line with a span per (x0, text) cell."""
    return Line(5, baseline, [Span(text, font[0], font[1], x, x + 5 * len(text)) for x, text in cells],
                1, 313.5, 540.0)


class TestIsTableLine:
    def test_given_table_and_body_fonts_when_tested_then_only_table_type_counts(self):
        # Given a cell line, a header line, a body line and a framed cell line
        framed = row(100, (317.1, "Strength"))
        framed.frame = 0

        # When each is tested
        # Then header and cells are table lines; body text and sidebars are not
        assert is_table_line(row(100, (317.1, "Strength")))
        assert is_table_line(row(100, (317.5, "Ability"), font=HEADER))
        assert not is_table_line(row(100, (313.5, "Each ability"), font=("Cambria", 10.0)))
        assert not is_table_line(framed)
        # And an italic word in a cell (Trinkets row 49) keeps it a table line
        assert is_table_line(row(341.8, (99.7, "A silver spoon with an "), (187.1, "M"),
                                 font=("GillSans-Italic", 9.5)))

    def test_given_a_bold_name_inside_a_cell_when_tested_then_the_line_is_a_table_line(self):
        # Given Bag of Beans (page 211): "A **Treant** sprouts", the name semibold at the cell size
        cell = row(67.9, (322.4, "11\u201320"), (366.5, "A "))
        cell.spans.append(Span("Treant", "GillSans-SemiBold", 9.5, 380.0, 410.0))
        label = row(499.8, (63.0, "Range:"), (100.0, "Touch"))
        label.spans[0].font = "GillSans-SemiBold"

        # When each is tested
        # Then the cell line is a table line; a line led by the label is not
        assert is_table_line(cell)
        assert not is_table_line(label)


class TestTableRun:
    def test_given_a_cell_wrapped_onto_a_line_led_by_a_bold_word_when_gathered_then_it_is_kept(self):
        # Given Amulet of the Planes' row 81-90 (page 209), its wrap led by a semibold "2,"
        lines = [row(300.0, (322.4, "81\u201390"), (366.5, "on a ")),
                 row(312.5, (366.5, "2,"), (380.0, " Acheron")),
                 row(327.6, (322.4, "91\u201300"), (366.5, "Astral Plane"))]
        lines[0].spans.append(Span("1,", "GillSans-SemiBold", 9.5, 390.0, 398.0))
        lines[1].spans[0].font = "GillSans-SemiBold"

        # When the table's lines are gathered
        # Then all three are the table's
        assert table_run(lines, 0) == lines


class TestTable:
    def test_given_a_header_and_rows_when_built_then_cells_fall_under_their_labels(self):
        # Given page 5's Ability Descriptions, cells 0.4pt left of the labels
        lines = [row(186.0, (317.5, "Ability"), (380.1, "Score Measures"), font=HEADER),
                 row(200.8, (317.1, "Strength"), (379.7, "Physical might")),
                 row(215.9, (317.1, "Dexterity"), (379.7, "Agility"))]

        # When the table is built
        built = table([Run("Ability Descriptions", bold=True)], lines, set())

        # Then the header and both rows have two cells each
        assert built.header == [[[Run("Ability", bold=True)], [Run("Score Measures", bold=True)]]]
        assert built.rows == [[[Run("Strength")], [Run("Physical might")]],
                              [[Run("Dexterity")], [Run("Agility")]]]
        assert built.pages == [5]

    def test_given_a_cell_wrapped_onto_more_lines_when_built_then_it_is_one_row(self):
        # Given Ability Scores' row "1", its meaning printed on three lines
        lines = [row(390.6, (322.4, "Score"), (358.5, "Meaning"), font=HEADER),
                 row(405.4, (331.6, "1"), (358.1, "This is the lowest. ")),
                 row(417.9, (358.1, "If an effect reduces it, ")),
                 row(430.4, (358.1, "that effect explains.")),
                 row(445.6, (326.7, "2–9"), (358.1, "Weak."))]

        # When the table is built
        built = table([], lines, set())

        # Then the wrapped lines join the row above them
        assert [[c[0].text for c in r] for r in built.rows] == [
            ["1", "This is the lowest. If an effect reduces it, that effect explains."],
            ["2–9", "Weak."]]

    def test_given_a_table_printed_in_two_halves_when_built_then_the_halves_stack(self):
        # Given page 6's Typical Difficulty Classes: labels repeated, the right half shorter
        lines = [row(900, (313.5, "Task Difficulty"), (400, "DC"), (433, "Task Difficulty"), (520, "DC"),
                     font=HEADER),
                 row(915, (313.5, "Very easy"), (400, "5"), (433, "Very hard"), (520, "25")),
                 row(930, (313.5, "Easy"), (400, "10"), (433, "Nearly impossible"), (520, "30")),
                 row(945, (313.5, "Medium"), (400, "15"))]

        # When the table is built
        built = table([], lines, set())

        # Then it is one two-column table, left half first, no empty rows
        assert [[c[0].text for c in r] for r in built.header] == [["Task Difficulty", "DC"]]
        assert [[c[0].text for c in r] for r in built.rows] == [
            ["Very easy", "5"], ["Easy", "10"], ["Medium", "15"],
            ["Very hard", "25"], ["Nearly impossible", "30"]]


    def test_given_a_label_over_several_columns_when_built_then_the_lower_labels_set_them(self):
        # Given page 12's Travel Pace: "Distance Traveled Per …" printed over Minute, Hour, Day
        lines = [row(433.5, (374.4, "Distance Traveled Per …"), font=HEADER),
                 row(448.2, (317.5, "Pace"), (374.4, "Minute"), (432.9, "Hour"), (486.2, "Day"),
                     font=HEADER),
                 row(463.0, (317.1, "Fast"), (374.0, "400 feet"), (432.5, "4 miles"), (485.8, "30 miles"))]

        # When the table is built
        built = table([], lines, set())

        # Then there are four columns, the spanning label kept over the first it covers
        assert [[plain(c) for c in r] for r in built.header] == [
            ["", "Distance Traveled Per …", "", ""], ["Pace", "Minute", "Hour", "Day"]]
        assert [plain(c) for c in built.rows[0]] == ["Fast", "400 feet", "4 miles", "30 miles"]


    def test_given_a_label_centred_over_its_column_when_built_then_it_heads_that_column(self):
        # Given page 28's "Proficiency" centred over "Bonus", starting left of it
        lines = [row(60, (98.0, "Proficiency"), font=HEADER),
                 row(72, (72.0, "Level"), (110.0, "Bonus"), font=HEADER),
                 row(87, (75.0, "1"), (112.0, "+2"))]

        # When the table is built
        built = table([], lines, set())

        # Then "Proficiency" sits over "Bonus", not over "Level"
        assert [[plain(c) for c in r] for r in built.header] == [["", "Proficiency"], ["Level", "Bonus"]]


    def test_given_a_label_starting_right_of_its_first_columns_centre_when_built_then_it_heads_that_column(self):
        # Given page 31's Bard Features: the dashed label starts at 393.8, over "1"
        # (390.7 to 395.6) but right of its centre
        lines = [row(377.5, (393.8, "Spell Slots per Spell Level"), font=HEADER),
                 row(388.9, (349.4, "Spells"), (390.7, "1"), (408.7, "2"), (426.7, "3"), font=HEADER),
                 row(403.7, (358.0, "4"), (390.5, "2"), (406.4, "\u2014"), (424.4, "\u2014"))]
        for span in lines[0].spans:
            span.x1 = 536.4
        for span in lines[1].spans[1:]:
            span.x1 = span.x0 + 4.9

        # When the table is built
        built = table([], lines, set())

        # Then the label sits over "1", the first level it spans
        assert [plain(c) for c in built.header[0]] == ["", "Spell Slots per Spell Level", "", ""]

    def test_given_a_dash_centred_under_a_digit_when_built_then_it_is_in_that_column(self):
        # Given page 26's Spell Slots: a dash starts 2.3pt left of the label "2"
        lines = [row(255.5, (68.4, "Level"), (103.4, "1"), (125.0, "2"), font=HEADER),
                 row(270.3, (76.6, "1"), (103.5, "2"), (122.7, "\u2014"))]

        # When the table is built
        # Then each value is under its label
        assert [plain(c) for c in table([], lines, set()).rows[0]] == ["1", "2", "\u2014"]

    def test_given_right_aligned_cells_when_built_then_each_is_under_the_label_it_overlaps(self):
        # Given page 91's Weight and Cost, right-aligned: "25 GP" starts left of "Cost"
        lines = [row(46.8, (476.6, "Weight"), (529.1, "Cost"), font=HEADER),
                 row(258.2, (491.5, "5 lb."), (525.2, "25 GP"))]
        lines[0].spans[0].x1, lines[0].spans[1].x1 = 507.6, 549.1
        lines[1].spans[0].x1, lines[1].spans[1].x1 = 507.9, 549.5

        # When the table is built
        # Then the cost is in the Cost column
        assert [plain(c) for c in table([], lines, set()).rows[0]] == ["5 lb.", "25 GP"]

    def test_given_rows_a_wrapped_lines_step_apart_when_shading_changes_then_they_are_two_rows(self):
        # Given page 27's rows 35 (shaded) and 36 (plain), 12.5pt apart
        lines = [row(52.7, (67.0, "1d100"), (100.1, "Trinket"), font=HEADER),
                 row(67.5, (74.8, "35"), (99.7, "A white glove")),
                 row(80.0, (74.8, "36"), (99.7, "A vest"))]
        for span in lines[1].spans:
            span.shaded = True

        # When the table is built
        # Then the change of shading separates the rows
        assert [[plain(c) for c in r] for r in table([], lines, set()).rows] == [
            ["35", "A white glove"], ["36", "A vest"]]

    def test_given_a_key_value_table_with_a_wrapped_label_when_built_then_no_row_is_lost(self):
        # Given page 28's Core Barbarian Traits: no header, labels semibold beside plain
        # values, and "Proficiencies" wrapped alone onto a line of its own
        lines = [row(123.2, (66.6, "Primary Ability"), font=HEADER),
                 row(138.3, (66.6, "Hit Point Die"), font=HEADER),
                 row(153.4, (66.6, "Saving Throw "), font=HEADER),
                 row(164.2, (66.6, "Proficiencies"), font=HEADER)]
        for line, value in zip(lines, ("Strength", "D12", "Strength and Constitution")):
            line.spans.append(Span(value, *CELL, 163.8, 200.0))

        # When the table is built
        built = table([], lines, set())

        # Then the first row is not taken for a header, and the wrapped label joins its row
        assert built.header == []
        assert [[plain(c) for c in r] for r in built.rows] == [
            ["Primary Ability", "Strength"], ["Hit Point Die", "D12"],
            ["Saving Throw Proficiencies", "Strength and Constitution"]]

    def test_given_a_header_partly_in_the_cell_font_when_built_then_it_is_the_header(self):
        # Given page 192's Travel Terrain: "Terrain" in the header font, "Search DC" not
        lines = [row(517.2, (67.0, "Terrain"), font=HEADER), row(532.0, (66.6, "Arctic"))]
        lines[0].spans.append(Span("Search DC", *CELL, 482.9, 525.8))
        lines[1].spans.append(Span("10", *CELL, 499.8, 509.0))

        # When the table is built
        built = table([], lines, set())

        # Then the first line is its header
        assert [plain(c) for c in built.header[0]] == ["Terrain", "Search DC"]
        assert [plain(c) for c in built.rows[0]] == ["Arctic", "10"]


class TestCategories:
    def test_given_a_category_row_when_built_then_only_its_indented_rows_are_under_it(self):
        # Given page 100's Tack: italic "Saddle", three rows indented 8pt, then "Sled" at the edge
        lines = [row(345.1, (317.5, "Item"), (450.6, "Weight"), (516.0, "Cost"), font=HEADER),
                 row(405.4, (317.1, "Feed per day"), (461.0, "10 lb."), (517.2, "5 CP")),
                 row(420.5, (317.1, "Saddle"), font=("GillSans-Italic", 9.5)),
                 row(435.7, (325.1, "Exotic"), (460.4, "40 lb."), (512.0, "60 GP")),
                 row(450.8, (325.1, "Military"), (460.5, "30 lb."), (512.0, "20 GP")),
                 row(481.0, (317.1, "Sled"), (455.4, "300 lb."), (512.0, "20 GP"))]

        # When the table is built
        built = table([], lines, set())

        # Then Exotic and Military are under Saddle (row 1), and Sled under nothing
        assert [plain(r[0]) for r in built.rows] == ["Feed per day", "Saddle", "Exotic", "Military", "Sled"]
        assert built.under == [None, None, 1, 1, None]

    def test_given_no_category_row_when_built_then_nothing_is_under_one(self):
        # Given page 5's Ability Descriptions
        lines = [row(186.0, (317.5, "Ability"), (380.1, "Score Measures"), font=HEADER),
                 row(200.8, (317.1, "Strength"), (379.7, "Physical might"))]

        # When the table is built
        # Then no row is under a category
        assert table([], lines, set()).under == []


class TestTableEnd:
    def test_given_a_second_header_a_row_step_below_when_measured_then_a_new_table_starts(self):
        # Given page 160's Scrying tables, the second header 24pt below the first's last row
        lines = [row(257.3, (67.0, "Your Knowledge"), (229.0, "Save Modifier"), font=HEADER),
                 row(272.4, (66.6, "Secondhand"), (251.4, "+5")),
                 row(287.5, (66.6, "Extensive"), (251.4, "\u22125")),
                 row(311.5, (67.0, "You Have"), (229.0, "Save Modifier"), font=HEADER),
                 row(326.6, (66.6, "Picture"), (251.4, "\u22122"))]

        # When the first table's end is measured
        # Then it ends before the second header
        assert table_end(lines) == 3

    def test_given_a_label_wrapped_onto_a_header_styled_line_when_measured_then_the_table_goes_on(self):
        # Given page 28's "Proficiencies", 10.8pt below "Saving Throw"
        lines = [row(153.4, (66.6, "Saving Throw "), font=HEADER),
                 row(164.2, (66.6, "Proficiencies"), font=HEADER),
                 row(179.1, (66.6, "Skill Proficiencies"), font=HEADER)]
        lines[0].spans.append(Span("Strength", *CELL, 163.8, 200.0))
        lines[2].spans.append(Span("Choose 2:", "GillSans-Italic", 9.5, 163.8, 200.0))

        # When measured
        # Then every line is the one table
        assert table_end(lines) == 3


class TestRepeatWidth:
    def test_given_header_labels_when_measured_then_the_repeating_unit_is_found(self):
        # Given halved, single-label halved, and ordinary headers
        # When measured
        # Then the unit is the labels before they repeat, or all of them
        assert repeat_width(["Score", "Modifier", "Score", "Modifier"]) == 2
        assert repeat_width(["Language", "Language"]) == 1
        assert repeat_width(["Ability", "Score Measures"]) == 2


def rows(*labels: str) -> list[list[list[Run]]]:
    """One-cell rows."""
    return [[[Run(label)]] for label in labels]


class TestExtendTable:
    def test_given_numbered_halves_when_extended_then_each_half_goes_on_in_order(self):
        # Given page 256's XP table: 0-10 beside 14-27, then 11-13 beside 28-30 (shortened)
        start = Table([], [], rows("0", "1/8", "14", "15"), [256], halves=[2, 2], indented=[False] * 4)
        rest = Table([], [], rows("11", "28"), [256], halves=[1, 1], indented=[False] * 2)

        # When the rest is added
        extend_table(start, rest)

        # Then the rows run in number order
        assert [plain(r[0]) for r in start.rows] == ["0", "1/8", "11", "14", "15", "28"]

    def test_given_unnumbered_halves_when_extended_then_they_flow_half_by_half(self):
        # Given pages 101-102's Food, Drink, and Lodging, printed in flowing halves
        start = Table([], [], rows("Ale", "Modest", "Comfortable", "Modest"), [101], halves=[2, 2],
                      indented=[False] * 4)
        rest = Table([], [], rows("Comfortable", "Wine"), [102], halves=[1, 1], indented=[False] * 2)

        # When the rest is added
        extend_table(start, rest)

        # Then the halves follow one another, as printed
        assert [plain(r[0]) for r in start.rows] == [
            "Ale", "Modest", "Comfortable", "Modest", "Comfortable", "Wine"]
        assert start.pages == [101, 102]

    def test_given_a_categorys_rows_broken_off_when_extended_then_they_stay_under_it(self):
        # Given page 101's "Meal" and its first member, and page 102's last
        meal = [[Run("Meal", italic=True)], []]
        start = Table([], [], [meal, [[Run("Squalid")], [Run("1 CP")]]], [101], halves=[2],
                      indented=[False, True])
        rest = Table([], [], [[[Run("Aristocratic")], [Run("6 SP")]]], [102], halves=[1], indented=[True])

        # When the rest is added
        extend_table(start, rest)

        # Then both members are under the category
        assert start.under == [None, 0, 0]


class TestWrapsField:
    def test_given_a_field_wrapped_atop_the_next_column_when_tested_then_it_is_the_fields(self):
        # Given page 94: "Variants: ... dul-" ends a column, "cimer (25 GP...)" hangs atop the next
        label = row(684.1, (63.0, "Variants:"), (100.0, " Bagpipes, dul-"))
        label.spans[0].font = "GillSans-SemiBold"
        label.column, label.left = 0, 63.0
        wrap = row(48.5, (321.5, "cimer (25 GP, 10 lb.)"))
        wrap.left = 313.5

        # When the wrapped line is tested
        # Then it belongs to the field, not to a table
        assert wraps_field([label, wrap], 1)
