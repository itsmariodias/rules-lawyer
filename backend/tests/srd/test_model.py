from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from rules_lawyer.srd.model import BLOCKS, Paragraph, Run, Table, add_page

RUN = TypeAdapter(Run)


class TestAddPage:
    def test_given_pages_when_a_page_is_added_then_they_stay_ascending_and_unique(self):
        # Given a block on pages 5 and 7
        pages = [5, 7]

        # When it is found on 6, then on 7 again
        add_page(pages, 6)
        add_page(pages, 7)

        # Then each page is listed once, in order
        assert pages == [5, 6, 7]


class TestRun:
    def test_given_runs_when_written_then_plain_is_a_string_and_styles_are_named(self):
        # Given a plain run and two styled ones
        # When written
        # Then a plain run is its text, and only the styles it has are stored
        assert RUN.dump_python(Run("plain")) == "plain"
        assert RUN.dump_python(Run("Fireball", italic=True)) == {"text": "Fireball", "italic": True}
        assert RUN.dump_python(Run("Bite.", True, True)) == {"text": "Bite.", "bold": True, "italic": True}

    def test_given_a_bare_string_when_read_then_it_is_a_plain_run(self):
        # Given a plain run as the JSON stores it
        # When read
        # Then it is a run with no style
        assert RUN.validate_python("plain") == Run("plain")


class TestBlocks:
    def test_given_unset_and_build_time_fields_when_written_then_they_are_left_out(self):
        # Given a paragraph with no role, and a table with no categories but halves recorded
        blocks = [Paragraph([Run("Text.")], [1]),
                  Table([], [], [[[Run("1")]]], [5], halves=[1], indented=[False])]

        # When written
        data = BLOCKS.dump_python(blocks)

        # Then only what the book says is stored, each block naming its type first
        assert data == [{"type": "paragraph", "runs": ["Text."], "pages": [1]},
                        {"type": "table", "caption": [], "header": [], "rows": [[["1"]]], "pages": [5]}]
        assert [next(iter(block)) for block in data] == ["type", "type"]

    def test_given_a_block_missing_a_field_when_read_then_the_error_names_its_path(self):
        # Given a paragraph with no pages, second in the list
        data = [{"type": "heading", "level": 1, "text": "Spells", "page": 104},
                {"type": "paragraph", "runs": ["Text."]}]

        # When read
        # Then the error names the block and the field
        with pytest.raises(ValidationError, match=r"1\.paragraph\.pages"):
            BLOCKS.validate_python(data)
