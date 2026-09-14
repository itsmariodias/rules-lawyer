"""
Read queries against the graph: full-text search, and one section by id.

Both return a :class:`Passage`, which carries the section id and character
range that resolve a citation back to ``srd_hierarchy.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from neo4j import Driver, GraphDatabase

from ..config import get_settings
from ..graph.schema import FULLTEXT_NAME

# Lucene reads these as syntax.  A rules question is natural language —
# "the target's AC (+2)" — so every one of them is escaped rather than
# interpreted, and the query is matched as words.
_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


def escape_lucene(query: str) -> str:
    return _LUCENE_SPECIAL.sub(r"\\\1", query).strip()


@lru_cache(maxsize=1)
def driver() -> Driver:
    """
    One driver for the process, unlike ``graph.loader.session``.

    The loader opens a driver per run because it runs once; a chat server
    answers continuously and wants the connection pool kept warm.
    """
    neo4j = get_settings().neo4j
    return GraphDatabase.driver(neo4j.uri, auth=neo4j.auth)


def query(cypher: str, parameters: dict[str, Any]) -> list[dict]:
    """
    Parameters are passed as a dict, never as keyword arguments: one of them
    is called ``query``, which is also ``Session.run``'s own first argument.
    """
    settings = get_settings().neo4j
    with driver().session(database=settings.database) as session:
        return session.run(cypher, parameters).data()


@dataclass(slots=True)
class Passage:
    """
    A citable piece of the book.

    ``section_id`` is the artifact's only globally unique stable identifier,
    so it is what a citation carries; ``char_start``/``char_end`` are what
    turn that citation into highlighted source text in the side panel.
    """

    section_id: str
    heading: str | None
    entity_type: str | None
    content: str | None
    page_start: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    labels: list[str] = field(default_factory=list)
    score: float | None = None

    @classmethod
    def from_row(cls, row: dict) -> "Passage":
        return cls(
            section_id=row["id"],
            heading=row.get("heading"),
            entity_type=row.get("entity_type"),
            content=row.get("content"),
            page_start=row.get("page_start"),
            char_start=row.get("char_start"),
            char_end=row.get("char_end"),
            # ``:Section`` is on every one of them and carries no information.
            labels=[l for l in row.get("labels") or [] if l != "Section"],
            score=row.get("score"),
        )

    def as_citation(self) -> dict:
        """The subset the UI needs to render a citation chip and open it."""
        return {
            "section_id": self.section_id,
            "heading": self.heading,
            "entity_type": self.entity_type,
            "page": self.page_start,
            "labels": self.labels,
        }

    def for_model(self, max_chars: int = 1200) -> str:
        """
        How a passage is spelled to the model.

        The id leads, because the system prompt asks for citations by id and
        the model copies what it can see.
        """
        body = (self.content or "").strip()
        if len(body) > max_chars:
            body = body[:max_chars].rsplit(" ", 1)[0] + " …"
        kind = self.entity_type or "section"
        return (f"[{self.section_id}] {self.heading or '(untitled)'} "
                f"({kind}, p.{self.page_start})\n{body}")


_SEARCH = f"""
CALL db.index.fulltext.queryNodes('{FULLTEXT_NAME}', $query, {{limit: $limit}})
YIELD node, score
RETURN node.id AS id, node.heading AS heading, node.entity_type AS entity_type,
       node.content AS content, node.page_start AS page_start,
       node.char_start AS char_start, node.char_end AS char_end,
       labels(node) AS labels, score
"""

_SEARCH_TYPED = _SEARCH.replace(
    "YIELD node, score",
    "YIELD node, score\nWITH node, score WHERE node.entity_type IN $types",
)


def search(text: str, limit: int = 8, types: list[str] | None = None) -> list[Passage]:
    """
    Lexical search over every section's heading and prose.

    Filtering happens after the index rather than before it: the full-text
    index is the only thing that can rank, so the limit is raised and the
    surplus discarded, instead of asking Neo4j to scan by ``entity_type``.
    """
    escaped = escape_lucene(text)
    if not escaped:
        return []
    if types:
        rows = query(_SEARCH_TYPED,
                     {"query": escaped, "limit": limit * 5, "types": types})
        rows = rows[:limit]
    else:
        rows = query(_SEARCH, {"query": escaped, "limit": limit})
    return [Passage.from_row(row) for row in rows]


_SECTION = """
MATCH (n:Section {id: $id})
OPTIONAL MATCH (parent:Section)-[:HAS_SUBSECTION]->(n)
OPTIONAL MATCH (n)-[:HAS_SUBSECTION]->(child:Section)
RETURN n.id AS id, n.heading AS heading, n.entity_type AS entity_type,
       n.content AS content, n.page_start AS page_start,
       n.char_start AS char_start, n.char_end AS char_end, labels(n) AS labels,
       parent.id AS parent_id, parent.heading AS parent_heading,
       collect(DISTINCT {id: child.id, heading: child.heading}) AS children
"""


def get_section(section_id: str) -> tuple[Passage, dict] | None:
    """One section, plus the two hops that let a reader move around it."""
    rows = query(_SECTION, {"id": section_id})
    if not rows:
        return None
    row = rows[0]
    context = {
        "parent": ({"id": row["parent_id"], "heading": row["parent_heading"]}
                   if row["parent_id"] else None),
        # ``collect`` over a missing OPTIONAL MATCH yields one null-filled map.
        "children": [c for c in row["children"] if c["id"]],
    }
    return Passage.from_row(row), context
