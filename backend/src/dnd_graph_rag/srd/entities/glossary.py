"""The glossary: every Rules Definitions term, the damage types and the poison types.

The damage and poison types have no heading of their own: the damage types
are the rows of the Damage Types table, and the poison types four bold-led
paragraphs in "Poison". Each names the section that defines it.
"""

from __future__ import annotations

from dnd_graph_rag.srd.entities.records import description, source
from dnd_graph_rag.srd.model import Paragraph, Section, Table, plain
from dnd_graph_rag.srd.output.render import render_runs
from dnd_graph_rag.srd.sections import walk
from dnd_graph_rag.srd.vocabulary import DamageType, EntityType, TermType


def glossary(sections: list[Section], pdf: str) -> list[dict]:
    """Every glossary term, then the damage types, then the poison types.

    Args:
        sections: The book's sections, glossary terms annotated.
        pdf: The PDF's file name, recorded in each record's ``source``.

    Returns:
        One record per term: ``name``, ``term_type``, ``description``,
        ``section_id`` and ``source``.

    Raises:
        ValueError: The Damage Types table does not list the 13 damage types.
    """
    terms = [record(s.term, s.term_type, description(s), s, pdf)
             for s in walk(sections) if s.entity_type == EntityType.GLOSSARY_TERM]
    damage = next(s for s in walk(sections) if len(s.blocks) == 1 and isinstance(s.blocks[0], Table)
                  and plain(s.blocks[0].caption) == "Damage Types")
    rows = [[plain(cell).strip() for cell in row] for row in damage.blocks[0].rows]
    if sorted(name for name, _ in rows) != sorted(DamageType):
        raise ValueError(f"the Damage Types table lists {[name for name, _ in rows]}, not the 13 damage types")
    damage_types = [record(name, TermType.DAMAGE_TYPE, examples, damage, pdf) for name, examples in rows]
    poison = next(s for s in walk(sections) if s.heading == "Poison")
    poison_types = []
    for block in poison.blocks:
        if isinstance(block, Paragraph) and block.runs[0].bold and not block.runs[0].italic:
            name = block.runs[0].text.strip().rstrip(".")
            poison_types.append(record(name, TermType.POISON_TYPE, render_runs(block.runs[1:]).strip(), poison, pdf))
    return terms + damage_types + poison_types


def record(name: str, term_type: TermType, text: str, section: Section, pdf: str) -> dict:
    """One glossary record."""
    return {"name": name, "term_type": term_type, "description": text, "section_id": section.id,
            "source": source(section, pdf)}
