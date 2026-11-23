"""One conversation as a file to download: markdown, Word or PDF.

Every format starts from the same markdown transcript.  Answers keep their
dotted section ids, as an answer's Copy does in the UI, and each ends with
the sections it cites and their pages, so the file still points into the
book once it has left the app.  Word and PDF are made from that markdown,
parsed by markdown-it, so the three files say the same thing.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

import docx
import pymupdf
from docx.text.paragraph import Paragraph
from markdown_it import MarkdownIt
from markdown_it.token import Token

# CommonMark and GFM tables, which answers use.  Raw HTML in an answer is
# printed as text, never rendered.
MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table")

# The SRD's CC BY 4.0 licence asks for this attribution wherever its
# material is shared, so it travels with every export.
ATTRIBUTION = (
    'This work includes material from the System Reference Document 5.2.1 '
    '("SRD 5.2.1") by Wizards of the Coast LLC, available at '
    'https://www.dndbeyond.com/srd. The SRD 5.2.1 is licensed under the '
    'Creative Commons Attribution 4.0 International License, available at '
    'https://creativecommons.org/licenses/by/4.0/legalcode.')

# PyMuPDF's Story lays out HTML with this CSS.  Points, on A4 with 54pt
# (three quarter inch) margins.
PDF_CSS = """
body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.35; }
h1 { font-size: 18pt; }
h2 { font-size: 13pt; margin-top: 14pt; }
h3, h4, h5, h6 { font-size: 11pt; }
table { border-collapse: collapse; }
th, td { border: 1px solid #999; padding: 3pt 6pt; }
code, pre { font-family: monospace; }
"""
PDF_MARGIN = 54

MONOSPACE = "Courier New"


class ExportFormat(StrEnum):
    """The file types a conversation exports to; the value is the query parameter."""

    MARKDOWN = "markdown"
    DOCX = "docx"
    PDF = "pdf"


MEDIA_TYPES = {
    ExportFormat.MARKDOWN: "text/markdown; charset=utf-8",
    ExportFormat.DOCX: ("application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document"),
    ExportFormat.PDF: "application/pdf",
}

EXTENSIONS = {
    ExportFormat.MARKDOWN: "md",
    ExportFormat.DOCX: "docx",
    ExportFormat.PDF: "pdf",
}


@dataclass(frozen=True)
class Export:
    """A rendered conversation, ready to send as a download."""

    file_name: str
    media_type: str
    content: bytes


def render(title: str, turns: list[dict], kind: ExportFormat,
           exported_on: date) -> Export:
    """Render a conversation as a file.

    Args:
        title: The thread's title, the document's heading and file name.
        turns: The conversation, as ``ChatService.history`` returns it.
        kind: The file type.
        exported_on: Printed under the title.

    Returns:
        The file's name, media type and bytes.
    """
    markdown = transcript(title, turns, exported_on)
    if kind is ExportFormat.DOCX:
        content = to_docx(markdown, title)
    elif kind is ExportFormat.PDF:
        content = to_pdf(markdown)
    else:
        content = markdown.encode()
    return Export(file_name(title, EXTENSIONS[kind]), MEDIA_TYPES[kind], content)


def transcript(title: str, turns: list[dict], exported_on: date) -> str:
    """A conversation as one markdown document.

    Args:
        title: The thread's title, the document's heading.
        turns: The conversation, as ``ChatService.history`` returns it.
        exported_on: Printed under the title.

    Returns:
        The markdown, ending in a newline.
    """
    parts = [f"# {title}",
             f"Exported from Rules Lawyer, {exported_on.day} {exported_on:%B %Y}"]

    for index, turn in enumerate(turns):
        if turn["role"] == "user":
            parts += ["## Question", turn["content"]]
            # A failed turn stores no answer.
            answered = index + 1 < len(turns) and turns[index + 1]["role"] == "assistant"
            if not answered:
                parts += ["## Answer", "_No answer was given._"]
            continue

        parts += ["## Answer", _below_answer(turn["content"])]
        sources = []
        for citation in turn.get("citations") or []:
            line = f"- [{citation['section_id']}]"
            if citation.get("heading"):
                line += f" {citation['heading']}"
            if citation.get("page") is not None:
                line += f" (p. {citation['page']})"
            sources.append(line)
        if sources:
            parts.append("Sources:\n\n" + "\n".join(sources))

    parts += ["---", ATTRIBUTION]
    return "\n\n".join(parts) + "\n"


def _below_answer(answer: str) -> str:
    """The answer with its headings two levels down, so they sit under "## Answer"."""
    lines: list[str | None] = list(answer.split("\n"))
    tokens = MARKDOWN.parse(answer)
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.map is None:
            continue
        start, end = token.map
        level = min(int(token.tag[1]) + 2, 6)
        lines[start] = "#" * level + " " + tokens[index + 1].content
        # A heading underlined with === or --- spans two lines.
        for row in range(start + 1, end):
            lines[row] = None
    return "\n".join(line for line in lines if line is not None)


def file_name(title: str, extension: str) -> str:
    """A file name for a conversation: its title in lower case, hyphenated.

    Args:
        title: The thread's title.
        extension: The file type's extension, without the dot.

    Returns:
        At most 60 ASCII letters, digits and hyphens before the extension;
        ``conversation`` if the title has none.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:60].strip("-")
    return f"{slug or 'conversation'}.{extension}"


def to_pdf(markdown: str) -> bytes:
    """Lay out markdown on A4 pages.

    Args:
        markdown: The document.

    Returns:
        The PDF's bytes.
    """
    story = pymupdf.Story(html=MARKDOWN.render(markdown), user_css=PDF_CSS)
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    page = pymupdf.paper_rect("a4")
    text_area = page + (PDF_MARGIN, PDF_MARGIN, -PDF_MARGIN, -PDF_MARGIN)
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(text_area)
        story.draw(device)
        writer.end_page()
    writer.close()
    return buffer.getvalue()


def to_docx(markdown: str, title: str) -> bytes:
    """Write markdown as a Word document in the default template's styles.

    Headings, paragraphs, bold, italic, code, nested lists, block quotes and
    tables are kept; links keep their text.

    Args:
        markdown: The document.
        title: Stored as the document's title property.

    Returns:
        The .docx file's bytes.
    """
    document = docx.Document()
    document.core_properties.title = title
    tokens = MARKDOWN.parse(markdown)
    lists: list[str] = []  # the open lists' tags, "ul" or "ol", innermost last
    number = ""  # an ordered item's "3. ", until its first paragraph takes it
    quoted = False
    rows: list[list[tuple[bool, Token]]] = []  # a table's cells: (header?, inline)

    # Containers open and close around their blocks; a heading, paragraph or
    # cell's text is the inline token after its opening token.
    for index, token in enumerate(tokens):
        match token.type:
            case "heading_open":
                heading = document.add_heading(level=int(token.tag[1]) - 1)
                _add_runs(heading, tokens[index + 1])
            case "bullet_list_open" | "ordered_list_open":
                lists.append(token.tag)
            case "bullet_list_close" | "ordered_list_close":
                lists.pop()
            case "list_item_open":
                number = f"{token.info}{token.markup} " if lists[-1] == "ol" else ""
            case "blockquote_open":
                quoted = True
            case "blockquote_close":
                quoted = False
            case "paragraph_open":
                # Word's own numbering would run on from one answer's list to
                # the next, so ordered items carry their number as text.
                style = None
                if lists:
                    depth = "" if len(lists) == 1 else f" {min(len(lists), 3)}"
                    style = ("List Bullet" if lists[-1] == "ul" else "List") + depth
                elif quoted:
                    style = "Quote"
                paragraph = document.add_paragraph(style=style)
                if number:
                    paragraph.add_run(number)
                    number = ""
                _add_runs(paragraph, tokens[index + 1])
            case "fence" | "code_block":
                code = document.add_paragraph(style="No Spacing")
                code.add_run(token.content.rstrip("\n")).font.name = MONOSPACE
            case "table_open":
                rows = []
            case "tr_open":
                rows.append([])
            case "th_open" | "td_open":
                rows[-1].append((token.type == "th_open", tokens[index + 1]))
            case "table_close":
                table = document.add_table(rows=len(rows), cols=len(rows[0]))
                table.style = "Table Grid"
                for row, cells in zip(table.rows, rows):
                    for cell, (is_header, inline) in zip(row.cells, cells):
                        _add_runs(cell.paragraphs[0], inline, bold=is_header)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _add_runs(paragraph: Paragraph, inline: Token, bold: bool = False) -> None:
    """Write an inline token's text into a paragraph as styled runs, all bold with ``bold``."""
    strong = italic = False
    for child in inline.children or []:
        match child.type:
            case "strong_open" | "strong_close":
                strong = child.type == "strong_open"
            case "em_open" | "em_close":
                italic = child.type == "em_open"
            case "text":
                run = paragraph.add_run(child.content)
                run.bold = bold or strong or None
                run.italic = italic or None
            case "code_inline":
                paragraph.add_run(child.content).font.name = MONOSPACE
            case "softbreak":
                paragraph.add_run(" ")
            case "hardbreak":
                paragraph.add_run().add_break()
