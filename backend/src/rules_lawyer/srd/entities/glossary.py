"""The glossary: every Rules Definitions term, the damage types and the poison types.

The damage and poison types have no heading of their own: the damage types
are the rows of the Damage Types table, and the poison types four bold-led
paragraphs in "Poison". Each names the section that defines it.
"""

from __future__ import annotations

from rules_lawyer.srd.entities.records import source
from rules_lawyer.srd.model import Paragraph, Section, plain
from rules_lawyer.srd.output.render import render_runs, section_text
from rules_lawyer.srd.sections import captioned_tables, walk
from rules_lawyer.srd.vocabulary import (
    Action,
    AreaOfEffect,
    Condition,
    DamageType,
    EntityType,
    TermType,
)


def glossary(sections: list[Section], pdf: str) -> list[dict]:
    """Every glossary term, then the damage types, then the poison types.

    Args:
        sections: The book's sections, glossary terms annotated.
        pdf: The PDF's file name, recorded in each record's ``source``.

    Returns:
        One record per term: ``name``, ``term_type``, ``description``,
        ``section_id`` and ``source``.

    Raises:
        ValueError: The glossary's conditions, actions or areas of effect, or the
            Damage Types table's rows, are not the vocabulary's.
    """
    terms = [record(s.term, s.term_type, section_text(s), s, pdf)
             for s in walk(sections) if s.entity_type == EntityType.GLOSSARY_TERM]
    for term_type, vocabulary in ((TermType.CONDITION, Condition), (TermType.ACTION, Action),
                                  (TermType.AREA_OF_EFFECT, AreaOfEffect)):
        names = sorted(term["name"] for term in terms if term["term_type"] == term_type)
        if names != sorted(vocabulary):
            raise ValueError(f"the glossary's {term_type} terms are {names}, not {sorted(vocabulary)}")
    damage = captioned_tables(sections)["Damage Types"]
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
    """One glossary record.

    Args:
        name: The term.
        term_type: What kind of term it is.
        text: Its description.
        section: The section defining it.
        pdf: The PDF's file name, recorded in ``source``.

    Returns:
        ``name``, ``term_type``, ``description``, ``section_id`` and ``source``.
    """
    return {"name": name, "term_type": term_type, "description": text, "section_id": section.id,
            "source": source(section, pdf)}
