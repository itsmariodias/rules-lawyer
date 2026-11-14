from __future__ import annotations

import json

import pytest

from dnd_graph_rag.srd.model import (
    Contents,
    Entry,
    Field,
    ListBlock,
    Paragraph,
    Run,
    Section,
    Sidebar,
    Source,
    StatBlock,
    StatSection,
    Table,
)
from dnd_graph_rag.srd.output.document import from_json, to_json

BLOCKS = [Paragraph([Run("Cast "), Run("Fireball", italic=True)], [1, 2]),
          Paragraph([Run("Quoted.")], [2], "quote"),
          Paragraph([Run("Bite.", bold=True, italic=True), Run(" Melee.")], [2]),
          Contents([Entry([Run("Spells", bold=True)], 104, 1), Entry([Run("Gaining Spells")], 104, 2)], [2]),
          ListBlock(True, [[Paragraph([Run("Do.")], [2])]], [2], 3),
          Sidebar([Run("Round Down", bold=True)], [Paragraph([Run("Whenever.")], [2])], [2]),
          Table([Run("Scores", bold=True)], [[[Run("Score", bold=True)]]], [[[Run("1")]]], [2]),
          Table([], [[[Run("Item", bold=True)], [Run("Cost", bold=True)]]],
                [[[Run("Saddle", italic=True)], []], [[Run("Exotic")], [Run("60 GP")]]], [100], [None, 0]),
          StatBlock("Aboleth", [Run("Large Aberration", italic=True)], [Field("AC", [Run("17")])],
                    [["Str", "21", "+5", "+5"]],
                    [StatSection("Traits", [Paragraph([Run("Amphibious.", True, True)], [258])])], [258])]


SECTIONS = [Section("1", "Legal Information", 1, BLOCKS[:-1], [
    Section("1.1", "Aboleth", 2, BLOCKS[-1:], [], Source(258, 258, 900, 1000))], Source(1, 258, 0, 1000))]


META = {"title": "SRD", "pdf": "SRD.pdf"}
RECORDS = {"creatures": [{"name": "Aboleth"}]}


class TestToJson:
    def test_given_sections_when_written_then_each_keeps_its_id_source_and_blocks(self):
        # Given a section holding blocks and a subsection, a paragraph printed across pages 1 and 2
        # When they become JSON, with a collection and the checks
        document = to_json(META, SECTIONS, RECORDS, {"problems": []})

        # Then meta, sections, collections and validation are written in that order
        assert list(document) == ["meta", "sections", "creatures", "validation"]
        section = document["sections"][0]
        assert (section["id"], section["heading"], section["level"]) == ("1", "Legal Information", 1)
        assert section["source"] == {"page_start": 1, "page_end": 258, "char_start": 0, "char_end": 1000}
        assert [b["type"] for b in section["blocks"][:2]] == ["paragraph", "paragraph"]
        assert section["blocks"][0]["pages"] == [1, 2]
        assert section["subsections"][0]["blocks"][0]["type"] == "statblock"


class TestFromJson:
    def test_given_written_json_when_read_back_then_the_sections_are_the_same(self):
        # Given the document written as JSON text
        text = json.dumps(to_json(META, SECTIONS, RECORDS, {}))

        # When the text is loaded and read back
        title, sections = from_json(json.loads(text))

        # Then the title comes from meta and nothing was lost on the way
        assert (title, sections) == ("SRD", SECTIONS)

    def test_given_an_unknown_block_type_when_read_then_it_is_refused(self):
        # Given a section holding a block type nothing reads
        document = to_json(META, SECTIONS, {}, {})
        document["sections"][0]["blocks"] = [{"type": "chart"}]

        # When it is read
        # Then the type is named in the error
        with pytest.raises(ValueError, match="chart"):
            from_json(document)
