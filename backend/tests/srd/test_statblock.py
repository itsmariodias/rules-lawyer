from __future__ import annotations

import pytest

from dnd_graph_rag.srd.pages import Line, Span
from dnd_graph_rag.srd.statblock import ability_rows, fields_of
from dnd_graph_rag.srd.model import Run

LABELS = Line(258, 177.0, [Span(t, "GillSans", 6.0, x, x + 14) for x, t in
                           ((101.9, "MOD"), (120.2, "SAVE"))], 0, 63.0, 290.0)


def scores(baseline: float, *abilities: tuple[str, str, str, str]) -> Line:
    """An ability line: per ability its name in small caps (first letter apart), then values."""
    spans = []
    for name, score, mod, save in abilities:
        spans += [Span(name[0], "GillSans-SemiBold-SC700", 9.8, 0, 0),
                  Span(name[1:], "GillSans-SemiBold-SC700", 6.8, 0, 0),
                  Span(f"\t{score} ", "GillSans", 9.8, 0, 0), Span(mod, "GillSans", 9.8, 0, 0),
                  Span(save, "GillSans", 9.8, 0, 0)]
    return Line(258, baseline, spans, 0, 63.0, 290.0)


class TestAbilityRows:
    def test_given_two_lines_of_scores_when_read_then_each_ability_is_a_row(self):
        # Given page 258's Aboleth, three abilities a line
        lines = [LABELS, scores(188.8, ("Str", "21", "+5", "+5"), ("Dex", "9", "\u22121", "+3")),
                 scores(203.0, ("Int", "18", "+4", "+8"))]

        # When the scores are read
        # Then each ability is a row of name, score, MOD and SAVE
        assert ability_rows(lines) == [
            ["Str", "21", "+5", "+5"], ["Dex", "9", "\u22121", "+3"], ["Int", "18", "+4", "+8"]]

    def test_given_a_name_set_in_bold_when_read_then_it_still_starts_a_row(self):
        # Given page 340: one "Con" set in GillSans-Bold, not small caps
        line = scores(131.1, ("Dex", "10", "+0", "+5"))
        line.spans += [Span("Con", "GillSans-Bold", 9.8, 0, 0), Span("\t22", "GillSans", 9.8, 0, 0),
                       Span("+6", "GillSans", 9.8, 0, 0), Span("+6", "GillSans", 9.8, 0, 0)]

        # When the scores are read
        # Then Con is a row of its own
        assert [r[0] for r in ability_rows([LABELS, line])] == ["Dex", "Con"]

    def test_given_an_ability_missing_a_value_when_read_then_it_is_an_error(self):
        # Given a line whose ability has a score and a modifier only
        line = scores(188.8, ("Str", "21", "+5", ""))

        # When read
        # Then it is refused, naming the page
        with pytest.raises(ValueError, match="page 258"):
            ability_rows([LABELS, line])


class TestFieldsOf:
    def test_given_two_labels_on_a_line_when_read_then_each_is_a_field(self):
        # Given page 258's "AC 17 Initiative +7 (17)", with an italic word in a later value
        runs = [Run("AC", bold=True), Run(" 17 "), Run("Initiative", bold=True), Run(" +7 (17) "),
                Run("Immunities", bold=True), Run(" Charmed (with "), Run("Mind Blank", italic=True),
                Run(")")]

        # When the fields are read
        fields = fields_of(runs)

        # Then each label has its value, trimmed, styles kept
        assert [(f.label, f.value) for f in fields] == [
            ("AC", [Run("17")]), ("Initiative", [Run("+7 (17)")]),
            ("Immunities", [Run("Charmed (with "), Run("Mind Blank", italic=True), Run(")")])]
