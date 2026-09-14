"""
The two tools the agent may call, over ``retrieval``'s two queries.

Results are prose rather than JSON: the model reads them, and every result
leads with its section id so the model can cite it.  The UI gets the
structured form by another route — ``service`` reads the tool calls off the
message stream — so nothing here serialises for two audiences at once.
"""

from __future__ import annotations

from langchain_core.tools import tool

from ..config import get_settings
from . import retrieval

# Entity types a question tends to be *about*, offered to the model as a
# filter.  Deliberately not the full list from the artifact: the long tail
# ("front_matter", "creature_group") narrows nothing a reader would ask for.
SEARCHABLE_TYPES = [
    "spell", "creature", "magic_item", "rule", "class_feature",
    "glossary_term", "equipment", "feat", "origin", "trap",
    "environmental_effect", "contagion",
]


@tool(parse_docstring=True)
def search_srd(query: str, entity_type: str | None = None) -> str:
    """Search the D&D 5e SRD for rules text matching a query.

    Args:
        query: Words to search for, such as "grappled condition" or
            "sneak attack damage". Natural language is fine; this is a
            keyword search, so prefer the terms the rulebook itself uses.
        entity_type: Optional filter, one of spell, creature, magic_item,
            rule, class_feature, glossary_term, equipment, feat, origin,
            trap, environmental_effect, contagion. Omit it unless the
            question is clearly about one kind of thing.
    """
    if entity_type and entity_type not in SEARCHABLE_TYPES:
        return (f"Unknown entity_type {entity_type!r}. "
                f"Valid values: {', '.join(SEARCHABLE_TYPES)}.")

    passages = retrieval.search(
        query,
        limit=get_settings().chat.search_limit,
        types=[entity_type] if entity_type else None,
    )
    if not passages:
        return (f"No SRD sections matched {query!r}. Try fewer words, or the "
                "term the rulebook uses.")
    return "\n\n---\n\n".join(passage.for_model() for passage in passages)


@tool(parse_docstring=True)
def get_srd_section(section_id: str) -> str:
    """Fetch the full text of one SRD section by its id.

    Use this when a search result is truncated, or to read a parent or child
    section that a previous result pointed at.

    Args:
        section_id: A dotted section id such as "11.2.46.1", exactly as it
            appears in square brackets in a search result.
    """
    found = retrieval.get_section(section_id.strip())
    if found is None:
        return (f"No section with id {section_id!r}. Ids come from search "
                "results and look like 5.3.12 or 11.2.46.1.")

    passage, context = found
    parts = [passage.for_model(max_chars=8000)]
    if context["parent"]:
        parts.append(f"Parent: [{context['parent']['id']}] "
                     f"{context['parent']['heading']}")
    if context["children"]:
        listed = ", ".join(f"[{c['id']}] {c['heading']}"
                           for c in context["children"][:25])
        parts.append(f"Subsections: {listed}")
    return "\n\n".join(parts)


TOOLS = [search_srd, get_srd_section]
