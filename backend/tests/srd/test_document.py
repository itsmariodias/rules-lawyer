from __future__ import annotations

import json

import pytest

from dnd_graph_rag.srd.model import (Contents, Entry, Field, Heading, ListBlock, Paragraph, Run,
                                     Section, Sidebar, StatBlock, Table)
from dnd_graph_rag.srd.document import from_json, run_json, to_json

BLOCKS = [Heading(1, "Legal Information", 1),
          Paragraph([Run("Cast "), Run("Fireball", italic=True)], [1, 2]),
          Paragraph([Run("Quoted.")], [2], "quote"),
          Paragraph([Run("Bite.", bold=True, italic=True), Run(" Melee.")], [2]),
          Contents([Entry([Run("Spells", bold=True)], 104, 1), Entry([Run("Gaining Spells")], 104, 2)], [2]),
          ListBlock(True, [[Paragraph([Run("Do.")], [2])]], [2], 3),
          Sidebar([Run("Round Down", bold=True)], [Paragraph([Run("Whenever.")], [2])], [2]),
          Table([Run("Scores", bold=True)], [[[Run("Score", bold=True)]]], [[[Run("1")]]], [2]),
          StatBlock("Aboleth", [Run("Large Aberration", italic=True)], [Field("AC", [Run("17")])],
                    [["Str", "21", "+5", "+5"]],
                    [Section("Traits", [Paragraph([Run("Amphibious.", True, True)], [258])])], [258])]


class TestToJson:
    def test_given_blocks_when_written_then_each_names_its_pages(self):
        # Given blocks, a paragraph among them printed across pages 1 and 2
        # When they become JSON
        document = to_json("SRD", BLOCKS)

        # Then the title is kept, blocks stay in order, and pages ride on each block
        assert document["title"] == "SRD"
        assert [b["type"] for b in document["blocks"][:3]] == ["heading", "paragraph", "paragraph"]
        assert document["blocks"][1]["pages"] == [1, 2]


class TestFromJson:
    def test_given_written_json_when_read_back_then_the_blocks_are_the_same(self):
        # Given the blocks written as JSON text
        text = json.dumps(to_json("SRD", BLOCKS))

        # When the text is loaded and read back
        title, blocks = from_json(json.loads(text))

        # Then nothing was lost on the way
        assert (title, blocks) == ("SRD", BLOCKS)

    def test_given_an_unknown_block_type_when_read_then_it_is_refused(self):
        # Given a document with a block type nothing reads
        document = {"title": "SRD", "blocks": [{"type": "chart"}]}

        # When it is read
        # Then the type is named in the error
        with pytest.raises(ValueError, match="chart"):
            from_json(document)


class TestRunJson:
    def test_given_runs_when_written_then_plain_is_a_string_and_styles_are_named(self):
        # Given a plain run and two styled ones
        # When written
        # Then a plain run is its text, and only the styles it has are stored
        assert run_json(Run("plain")) == "plain"
        assert run_json(Run("Fireball", italic=True)) == {"text": "Fireball", "italic": True}
        assert run_json(Run("Bite.", True, True)) == {"text": "Bite.", "bold": True, "italic": True}
