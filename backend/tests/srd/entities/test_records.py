from __future__ import annotations

from dnd_graph_rag.srd.entities.records import labelled_fields, named_entries
from dnd_graph_rag.srd.model import Paragraph, Run


class TestLabelledFields:
    def test_given_labels_sharing_a_line_when_read_then_each_is_a_field_and_the_first_wins(self):
        # Given page 93's tool line, and a repeated label
        paragraphs = [Paragraph([Run("Ability:", bold=True), Run(" Wisdom "), Run("Weight:", bold=True),
                                 Run(" 3 lb.")], [93]),
                      Paragraph([Run("Ability:", bold=True), Run(" Strength")], [93])]

        # When read
        # Then both labels are fields, keyed in snake case, and the repeat is ignored
        assert labelled_fields(paragraphs) == {"ability": "Wisdom", "weight": "3 lb."}


class TestNamedEntries:
    def test_given_entries_and_a_continuation_when_read_then_the_blocks_are_left_unchanged(self):
        # Given an intro, a named trait, and a paragraph continuing it
        trait = Paragraph([Run("Darkvision.", bold=True, italic=True), Run(" You see"), Run(" in the dark.")], [84])
        more = Paragraph([Run("It lasts.")], [84])
        paragraphs = [Paragraph([Run("You have these traits.")], [84]), trait, more]

        # When read
        found = named_entries(paragraphs)

        # Then the intro is skipped, the continuation joins, and the book's runs are not merged in place
        assert [(name, "".join(r.text for r in runs)) for name, runs in found] == [
            ("Darkvision", " You see in the dark. It lasts.")]
        assert [r.text for r in trait.runs] == ["Darkvision.", " You see", " in the dark."]
