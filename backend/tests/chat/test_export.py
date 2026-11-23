from __future__ import annotations

import io
from datetime import date

import docx
import pymupdf
import pytest

from rules_lawyer.chat.export import (
    ATTRIBUTION,
    ExportFormat,
    file_name,
    render,
    to_docx,
    to_pdf,
    transcript,
)

EXPORTED_ON = date(2026, 11, 23)

PRONE = [
    {"role": "user", "content": "What does Prone do?"},
    {"role": "assistant",
     "content": "A Prone creature has Disadvantage on attack rolls [11.2.114].",
     "citations": [{"section_id": "11.2.114", "heading": "Prone",
                    "entity_type": "glossary_term", "page": 189, "labels": []}]},
]


def docx_text(content: bytes) -> list[str]:
    """A Word file's paragraphs, then its table cells, as text."""
    document = docx.Document(io.BytesIO(content))
    cells = [cell.text for table in document.tables
             for row in table.rows for cell in row.cells]
    return [p.text for p in document.paragraphs] + cells


class TestTranscript:
    def test_given_a_conversation_when_exported_then_it_opens_with_title_and_date(self):
        # Given a titled thread
        # When it is exported
        markdown = transcript("Prone condition", PRONE, EXPORTED_ON)

        # Then it opens with the title and when it was made
        assert markdown.startswith(
            "# Prone condition\n\nExported from Rules Lawyer, 23 November 2026\n\n")

    def test_given_a_conversation_when_exported_then_each_turn_is_a_question_and_answer(self):
        # Given a question and its answer
        # When it is exported
        markdown = transcript("Prone condition", PRONE, EXPORTED_ON)

        # Then both are there, in order, the answer with its dotted id
        assert ("## Question\n\nWhat does Prone do?\n\n## Answer\n\n"
                "A Prone creature has Disadvantage on attack rolls [11.2.114].") in markdown

    def test_given_a_cited_answer_when_exported_then_its_sources_follow_with_pages(self):
        # Given an answer citing a section of the book
        # When it is exported
        markdown = transcript("Prone condition", PRONE, EXPORTED_ON)

        # Then the file says where the claim came from without the app
        assert "Sources:\n\n- [11.2.114] Prone (p. 189)" in markdown

    def test_given_a_citation_without_heading_or_page_when_exported_then_the_id_stands_alone(
            self):
        # Given a citation the graph could say little about
        turns = [{"role": "assistant", "content": "See [9.7.6].",
                  "citations": [{"section_id": "9.7.6", "heading": None,
                                 "page": None}]}]

        # When it is exported
        # Then the id is listed with nothing invented around it
        assert "Sources:\n\n- [9.7.6]\n" in transcript("Spells", turns, EXPORTED_ON)

    def test_given_answers_with_no_citations_when_exported_then_no_sources_are_listed(self):
        # Given an answer read back while the graph was down
        turns = [{"role": "assistant", "content": "See [9.7.6].", "citations": []}]

        # When it is exported
        # Then there is no empty Sources list
        assert "Sources" not in transcript("Spells", turns, EXPORTED_ON)

    @pytest.mark.parametrize("after", [[], [{"role": "user", "content": "Again?"}]])
    def test_given_a_question_without_an_answer_when_exported_then_the_gap_is_said(
            self, after):
        # Given a question whose turn failed, last or followed by another
        turns = [{"role": "user", "content": "What does Prone do?"}, *after]

        # When it is exported
        markdown = transcript("Prone", turns, EXPORTED_ON)

        # Then the reader sees there was no answer rather than two questions in a row
        assert ("What does Prone do?\n\n## Answer\n\n_No answer was given._"
                in markdown)

    def test_given_an_answer_with_headings_when_exported_then_they_sit_under_answer(self):
        # Given an answer with headings of its own, one underlined
        answer = "## Movement\n\nCrawl.\n\nAttacks\n-------\n\nDisadvantage."
        turns = [{"role": "assistant", "content": answer, "citations": []}]

        # When it is exported
        markdown = transcript("Prone", turns, EXPORTED_ON)

        # Then both are two levels down, below the answer's own heading
        assert "## Answer\n\n#### Movement\n\nCrawl.\n\n#### Attacks\n\nDisadvantage." in markdown

    def test_given_a_deep_heading_when_exported_then_it_stays_a_heading(self):
        # Given an answer with a level 5 heading
        turns = [{"role": "assistant", "content": "##### Note", "citations": []}]

        # When it is exported
        # Then it goes no deeper than markdown allows
        assert "\n###### Note\n" in transcript("Prone", turns, EXPORTED_ON)

    def test_given_any_conversation_when_exported_then_it_ends_with_the_srd_attribution(self):
        # Given a conversation quoting the SRD
        # When it is exported
        markdown = transcript("Prone condition", PRONE, EXPORTED_ON)

        # Then the licence's attribution goes with it
        assert markdown.endswith(f"---\n\n{ATTRIBUTION}\n")


class TestFileName:
    @pytest.mark.parametrize(("title", "name"), [
        ("Prone condition", "prone-condition.pdf"),
        ("How does a Rogue’s Sneak Attack scale?", "how-does-a-rogue-s-sneak-attack-scale.pdf"),
        ("  Fireball: 8d6!  ", "fireball-8d6.pdf"),
    ])
    def test_given_a_title_when_named_then_it_is_lower_case_and_hyphenated(
            self, title, name):
        # Given a thread's title
        # When it names a file
        # Then the name is its words in lower case, joined by hyphens
        assert file_name(title, "pdf") == name

    def test_given_a_long_title_when_named_then_it_is_cut_without_a_trailing_hyphen(self):
        # Given a title past 60 characters whose cut lands after a space
        title = "a" * 59 + " b"

        # When it names a file
        # Then the cut leaves no dangling hyphen
        assert file_name(title, "md") == "a" * 59 + ".md"

    def test_given_a_title_with_no_ascii_letters_when_named_then_it_is_conversation(self):
        # Given a title of punctuation only
        # When it names a file
        # Then a name is still made
        assert file_name("?!", "docx") == "conversation.docx"


class TestToDocx:
    def test_given_a_transcript_when_written_then_word_has_the_same_text(self):
        # Given a conversation as markdown
        markdown = transcript("Prone condition", PRONE, EXPORTED_ON)

        # When it is written as a Word document
        text = docx_text(to_docx(markdown, "Prone condition"))

        # Then headings, answer and sources read as they do in the markdown
        assert text[:2] == ["Prone condition",
                            "Exported from Rules Lawyer, 23 November 2026"]
        assert "A Prone creature has Disadvantage on attack rolls [11.2.114]." in text
        assert "[11.2.114] Prone (p. 189)" in text
        assert ATTRIBUTION in text

    def test_given_markdown_structure_when_written_then_word_styles_carry_it(self):
        # Given headings, a bulleted and a numbered list, and a quote
        markdown = "# Title\n\n## Part\n\n- one\n  - inner\n\n3. third\n\n> quoted\n"

        # When it is written as a Word document
        document = docx.Document(io.BytesIO(to_docx(markdown, "Title")))

        # Then each block has the matching style, numbers written as printed
        styled = [(p.style.name, p.text) for p in document.paragraphs]
        assert styled == [("Title", "Title"), ("Heading 1", "Part"),
                          ("List Bullet", "one"), ("List Bullet 2", "inner"),
                          ("List", "3. third"), ("Quote", "quoted")]

    def test_given_bold_and_italic_when_written_then_runs_keep_them(self):
        # Given an answer with emphasis
        # When it is written as a Word document
        document = docx.Document(io.BytesIO(to_docx("A **Prone** _creature_.", "x")))

        # Then the runs say which words were bold and which italic
        runs = [(r.text, bool(r.bold), bool(r.italic))
                for r in document.paragraphs[0].runs]
        assert runs == [("A ", False, False), ("Prone", True, False),
                        (" ", False, False), ("creature", False, True),
                        (".", False, False)]

    def test_given_a_table_when_written_then_word_has_a_table_with_a_bold_header(self):
        # Given an answer with a table
        markdown = "| Level | Dice |\n| --- | --- |\n| 1 | 1d6 |\n| 3 | 2d6 |\n"

        # When it is written as a Word document
        document = docx.Document(io.BytesIO(to_docx(markdown, "x")))

        # Then the rows come through, the header row bold
        [table] = document.tables
        assert [[c.text for c in row.cells] for row in table.rows] == [
            ["Level", "Dice"], ["1", "1d6"], ["3", "2d6"]]
        assert all(run.bold for run in table.rows[0].cells[0].paragraphs[0].runs)

    def test_given_a_title_when_written_then_it_is_the_document_property(self):
        # Given a thread's title
        # When it is written as a Word document
        document = docx.Document(io.BytesIO(to_docx("Text.", "Prone condition")))

        # Then Word shows it as the document's title
        assert document.core_properties.title == "Prone condition"


class TestToPdf:
    def test_given_a_transcript_when_laid_out_then_the_pdf_reads_the_same(self):
        # Given a conversation as markdown
        markdown = transcript("Prone condition", PRONE, EXPORTED_ON)

        # When it is laid out as a PDF
        with pymupdf.open(stream=to_pdf(markdown), filetype="pdf") as pdf:
            text = " ".join(page.get_text() for page in pdf)

        # Then the title, the cited answer and its source are on the page
        for expected in ("Prone condition", "[11.2.114]", "Prone (p. 189)", "SRD 5.2.1"):
            assert expected in text

    def test_given_a_long_conversation_when_laid_out_then_it_runs_onto_more_pages(self):
        # Given more text than one page holds
        markdown = "\n\n".join(f"Paragraph {n} of a long answer." for n in range(200))

        # When it is laid out
        with pymupdf.open(stream=to_pdf(markdown), filetype="pdf") as pdf:
            # Then nothing is cut: the last paragraph is on the last page
            assert pdf.page_count > 1
            assert "Paragraph 199" in pdf[-1].get_text()


class TestRender:
    @pytest.mark.parametrize(("kind", "media_type", "name"), [
        (ExportFormat.MARKDOWN, "text/markdown; charset=utf-8", "prone-condition.md"),
        (ExportFormat.DOCX, ("application/vnd.openxmlformats-officedocument"
                             ".wordprocessingml.document"), "prone-condition.docx"),
        (ExportFormat.PDF, "application/pdf", "prone-condition.pdf"),
    ])
    def test_given_a_format_when_rendered_then_the_file_is_typed_and_named(
            self, kind, media_type, name):
        # Given a conversation and a file type
        # When it is rendered
        exported = render("Prone condition", PRONE, kind, EXPORTED_ON)

        # Then the download is named and typed for it
        assert (exported.media_type, exported.file_name) == (media_type, name)
        assert exported.content

    def test_given_markdown_when_rendered_then_the_file_is_the_transcript(self):
        # Given a conversation
        # When it is rendered as markdown
        exported = render("Prone condition", PRONE, ExportFormat.MARKDOWN, EXPORTED_ON)

        # Then the file is exactly the transcript, as UTF-8
        assert exported.content.decode() == transcript("Prone condition", PRONE, EXPORTED_ON)
