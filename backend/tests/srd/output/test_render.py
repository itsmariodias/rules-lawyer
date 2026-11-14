from __future__ import annotations

from dnd_graph_rag.srd.model import (
    Contents,
    Entry,
    Field,
    Heading,
    ListBlock,
    Paragraph,
    Run,
    Section,
    Sidebar,
    StatBlock,
    Table,
)
from dnd_graph_rag.srd.output.render import render, render_book, render_run


class TestRender:
    def test_given_a_heading_and_paragraphs_when_rendered_then_blank_lines_separate_them(self):
        # Given a heading, a paragraph and a quote
        blocks = [Heading(1, "Legal Information", 1),
                  Paragraph([Run("Free of charge.")], [1]),
                  Paragraph([Run("This work includes material.")], [1], "quote")]

        # When the blocks are rendered
        markdown = render(blocks)

        # Then each is one chunk, the quote as a blockquote, ending in a newline
        assert markdown == ("# Legal Information\n\nFree of charge.\n\n"
                            "> This work includes material.\n")

    def test_given_a_paragraph_starting_with_a_marker_when_rendered_then_it_is_escaped(self):
        # Given text that markdown would read as a list or heading
        blocks = [Paragraph([Run("1. Roll.")], [1]), Paragraph([Run("# of dice")], [1])]

        # When rendered
        # Then the marker is literal
        assert render(blocks) == "1\\. Roll.\n\n\\# of dice\n"


    def test_given_contents_when_rendered_then_entries_nest_by_level_with_pages(self):
        # Given a chapter entry and two levels beneath it
        block = Contents([Entry([Run("Playing the Game", bold=True)], 5, 1),
                          Entry([Run("D20 Tests")], 6, 2),
                          Entry([Run("Ability Checks")], 6, 3)], [2])

        # When rendered
        # Then each entry is a list item, nested by level, its page after it
        assert render([block]) == ("- **Playing the Game** (p. 5)\n"
                                   "  - D20 Tests (p. 6)\n"
                                   "    - Ability Checks (p. 6)\n")


    def test_given_a_numbered_list_when_rendered_then_items_are_numbered_from_its_start(self):
        # Given a list starting at 1 with a bold lead in each item
        block = ListBlock(True, [[Paragraph([Run("The GM Describes.", bold=True), Run(" The GM")], [5])],
                                 [Paragraph([Run("Do.")], [5])]], [5], 1)

        # When rendered
        # Then each item is one numbered line
        assert render([block]) == "1. **The GM Describes.** The GM\n2. Do.\n"

    def test_given_a_sidebar_when_rendered_then_it_is_a_blockquote_under_its_title(self):
        # Given a sidebar of two paragraphs
        block = Sidebar([Run("Round Down", bold=True)],
                        [Paragraph([Run("One.")], [5]), Paragraph([Run("Two.")], [5])], [5])

        # When rendered
        # Then every line is quoted, blank lines kept as bare markers
        assert render([block]) == "> **Round Down**\n>\n> One.\n>\n> Two.\n"

    def test_given_a_table_when_rendered_then_it_is_gfm_under_its_caption(self):
        # Given a captioned table whose header is bold in the book and a cell holds a pipe
        block = Table([Run("Ability Scores", bold=True)],
                      [[[Run("Score", bold=True)], [Run("Meaning", bold=True)]]],
                      [[[Run("1")], [Run("Lowest | rare")]]], [5])

        # When rendered
        # Then the header is plain (GFM bolds it) and the pipe is escaped
        assert render([block]) == ("**Ability Scores**\n\n| Score | Meaning |\n| --- | --- |\n"
                                   "| 1 | Lowest \\| rare |\n")

    def test_given_a_header_of_two_lines_when_rendered_then_each_column_joins_its_labels(self):
        # Given Travel Pace's header: a label over Minute, then the column labels
        block = Table([], [[[], [Run("Distance Traveled Per …")]], [[Run("Pace")], [Run("Minute")]]],
                      [[[Run("Fast")], [Run("400 feet")]]], [12])

        # When rendered
        # Then GFM's one header row holds both lines, top to bottom
        assert render([block]).splitlines()[0] == "| Pace | Distance Traveled Per … Minute |"

    def test_given_a_stat_block_when_rendered_then_the_scores_follow_speed(self):
        # Given a stat block with fields either side of its scores and one section
        block = StatBlock("Aboleth", [Run("Large Aberration, Lawful Evil", italic=True)],
                          [Field("AC", [Run("17")]), Field("Speed", [Run("10 ft.")]),
                           Field("CR", [Run("10")])],
                          [["Str", "21", "+5", "+5"]],
                          [Section("Traits", [Paragraph([Run("Amphibious.", True, True),
                                                         Run(" Breathes air.")], [258])])], [258])

        # When rendered
        # Then the name is the deepest heading, a field a line, the scores a table after Speed
        assert render([block]) == (
            "###### Aboleth\n\n_Large Aberration, Lawful Evil_\n\n**AC** 17\n\n**Speed** 10 ft.\n\n"
            "| Ability | Score | MOD | SAVE |\n| --- | --- | --- | --- |\n| Str | 21 | +5 | +5 |\n\n"
            "**CR** 10\n\n**Traits**\n\n**_Amphibious._** Breathes air.\n")


class TestRenderRun:
    def test_given_styled_runs_when_rendered_then_the_emphasis_matches(self):
        # Given a run in each style
        # When rendered
        # Then italic is underscores, bold is asterisks, both nest
        assert render_run(Run("Fireball", italic=True)) == "_Fireball_"
        assert render_run(Run("Rage.", bold=True)) == "**Rage.**"
        assert render_run(Run("Bite.", bold=True, italic=True)) == "**_Bite._**"

    def test_given_edge_whitespace_when_rendered_then_it_sits_outside_the_markers(self):
        # Given an italic run with a space on each side
        # When rendered
        # Then the spaces are outside, where markdown can close emphasis
        assert render_run(Run(" Fireball ", italic=True)) == " _Fireball_ "

    def test_given_markdown_characters_when_rendered_then_they_are_escaped(self):
        # Given text containing emphasis characters
        # When rendered
        # Then they stay literal
        assert render_run(Run("2*3 and snake_case")) == "2\\*3 and snake\\_case"


class TestRenderBook:
    def test_given_a_title_and_blocks_when_rendered_then_the_title_heads_the_book(self):
        # Given a title and a paragraph printed across pages 1 and 2
        blocks = [Paragraph([Run("One and two.")], [1, 2])]

        # When the book is rendered
        markdown = render_book("System Reference Document 5.2.1", blocks)

        # Then the title heads the book and no page break shows
        assert markdown == "# System Reference Document 5.2.1\n\nOne and two.\n"

    def test_given_book_headings_when_rendered_then_they_keep_the_books_level(self):
        # Given the book's own level 1 and level 5 headings
        # When rendered
        # Then each keeps its level, beside the title rather than under it
        assert render([Heading(1, "Legal Information", 1)]) == "# Legal Information\n"
        assert render([Heading(5, "Bite", 1)]) == "##### Bite\n"
