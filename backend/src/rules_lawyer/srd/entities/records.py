"""What every kind of record reads the same way: a section's text, its place, its named
entries and its labelled fields."""

from __future__ import annotations

import re

from rules_lawyer.srd.model import Paragraph, Run, Section
from rules_lawyer.srd.reading.text import merged


def source(section: Section, pdf: str) -> dict:
    """Where a record is printed: the PDF and the section's pages.

    Args:
        section: The section printing the record.
        pdf: The PDF's file name.

    Returns:
        ``{"pdf", "page_start", "page_end"}``.
    """
    return {"pdf": pdf, "page_start": section.source.page_start, "page_end": section.source.page_end}


def named_entries(paragraphs: list[Paragraph]) -> list[tuple[str, list[Run]]]:
    """Each entry's name and text.

    An entry opens with its name in bold italics ("**_Rage._**"); any other
    paragraph continues the entry before it, and one before the first entry is
    skipped ("As a Dragonborn, you have these special traits.").

    Args:
        paragraphs: The paragraphs to read, in order.

    Returns:
        ``(name, runs)`` per entry, the runs copies of the book's.
    """
    named: list[tuple[str, list[Run]]] = []
    for paragraph in paragraphs:
        lead, *rest = paragraph.runs
        if lead.bold and lead.italic:
            named.append((lead.text.strip().rstrip(".:"), rest))
        elif named:
            named[-1][1].extend([Run(" "), *paragraph.runs])
    # Copies: merging joins runs in place, and the blocks are the book's.
    return [(name, merged([Run(run.text, run.bold, run.italic) for run in runs])) for name, runs in named]


def labelled_fields(paragraphs: list[Paragraph]) -> dict[str, str]:
    """The fields printed as a bold label and its value ("**Creature Type:** Humanoid").

    There may be several to a paragraph; the first of a label wins.

    Args:
        paragraphs: The paragraphs to read.

    Returns:
        The label in snake case to its value, whitespace collapsed.
    """
    fields: dict[str, str] = {}
    for paragraph in paragraphs:
        label = None    # the label whose value is being read; None after a repeated one
        for run in paragraph.runs:
            text = run.text.strip()
            if run.bold and not run.italic and text.endswith(":"):
                key = re.sub(r"[^a-z0-9]+", "_", text[:-1].lower()).strip("_")
                label = None if key in fields else key
                if label:
                    fields[label] = ""
            elif label is not None:
                fields[label] += run.text
    return {label: " ".join(value.split()) for label, value in fields.items()}


def paragraphs_of(section: Section) -> list[Paragraph]:
    """The section's own paragraphs, in order.

    Args:
        section: A section.

    Returns:
        Its paragraph blocks, not its subsections'.
    """
    return [block for block in section.blocks if isinstance(block, Paragraph)]
