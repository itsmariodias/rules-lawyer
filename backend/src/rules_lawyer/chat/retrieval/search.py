"""Graph reads for retrieval: lexical (BM25 via Lucene), dense (``srd_vector``),
their rank fusion, and one section by id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from neo4j import Driver, GraphDatabase

from rules_lawyer.config import get_settings
from rules_lawyer.graph import embeddings
from rules_lawyer.graph.schema import FULLTEXT_NAME, VECTOR_NAME

# Lucene syntax characters, which questions like "AC (+2)" contain.
_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


def escape_lucene(query: str) -> str:
    """A question with every Lucene syntax character escaped, then stripped.

    Args:
        query: The question as asked.

    Returns:
        Text the full-text index reads as words only.
    """
    return _LUCENE_SPECIAL.sub(r"\\\1", query).strip()


# A citation as the model writes it: one dotted section id, or several in
# one bracket, e.g. [11.2.114] or [9.7.6, 9.7.7]; "[see below]" and "[3]" do
# not match.  ``frontend/src/chat/Markdown.tsx`` has a copy, which
# ``tests/test_docs.py`` holds against this one.
CITATION = re.compile(r"\[(\d+(?:\.\d+)+(?:\s*[,;]\s*\d+(?:\.\d+)+)*)\]")

# Between the ids of one citation.
_CITED_ID_SEPARATOR = re.compile(r"\s*[,;]\s*")


def cited_ids(text: str) -> list[str]:
    """Every section id cited in a text, in order, repeats included.

    Args:
        text: An answer, or anything else carrying ``CITATION``s.

    Returns:
        One entry per id: ``[9.7.6, 9.7.7]`` gives both ids.
    """
    ids = []
    for citation in CITATION.findall(text):
        ids.extend(_CITED_ID_SEPARATOR.split(citation))
    return ids


@lru_cache(maxsize=1)
def driver() -> Driver:
    """The process-wide driver, so the connection pool is reused across turns.

    Returns:
        A driver for the configured database.
    """
    neo4j = get_settings().neo4j
    return GraphDatabase.driver(neo4j.uri, auth=neo4j.auth)


def query(cypher: str, parameters: dict[str, Any]) -> list[dict]:
    """Run a read and return its rows.

    Parameters go as a dict, never as kwargs: one is named ``query``, which
    collides with ``Session.run``'s first parameter.

    Args:
        cypher: The statement.
        parameters: Its parameters.

    Returns:
        Each record as a dict.
    """
    settings = get_settings().neo4j
    with driver().session(database=settings.database) as session:
        return session.run(cypher, parameters).data()


@dataclass(slots=True)
class Passage:
    """A section returned by a search or lookup.

    Attributes:
        section_id: The dotted id the model cites.
        char_start: Offset of the section in ``srd_hierarchy.md``.
        char_end: End offset, exclusive.
        score: The index's score, or the fused score after ``fuse``.
        found_by: Search arms that returned it, e.g. ``["lexical"]``.
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
    found_by: list[str] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: dict) -> Passage:
        """Build from a search row, dropping the ``Section`` label.

        Args:
            row: A row of ``_SEARCH``, ``_VECTOR`` or ``_SECTION``.

        Returns:
            The passage; ``found_by`` is left for ``fuse`` to fill.
        """
        return cls(
            section_id=row["id"],
            heading=row.get("heading"),
            entity_type=row.get("entity_type"),
            content=row.get("content"),
            page_start=row.get("page_start"),
            char_start=row.get("char_start"),
            char_end=row.get("char_end"),
            labels=[label for label in row.get("labels") or []
                    if label != "Section"],
            score=row.get("score"),
        )

    def as_citation(self) -> dict:
        """The fields the UI's citation list reads.

        Returns:
            ``{"section_id", "heading", "entity_type", "page", "labels"}``.
        """
        return {
            "section_id": self.section_id,
            "heading": self.heading,
            "entity_type": self.entity_type,
            "page": self.page_start,
            "labels": self.labels,
        }

    def for_model(self, max_chars: int = 1200) -> str:
        """The passage as the model reads it, led by ``[id]`` for citing.

        Args:
            max_chars: Content is cut at a word boundary past this.

        Returns:
            A header line, then the content.
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
    """Full-text (BM25) search over section headings and content.

    With ``types``, the index is asked for ``5 * limit`` and filtered, since
    the index cannot filter before ranking.

    Args:
        text: The question, escaped before querying.
        limit: Maximum passages.
        types: Restrict to these ``entity_type`` values.

    Returns:
        Passages in score order; empty for a blank question.
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


# --------------------------------------------------------------------------
# The dense arm


# Gemini embeds documents as RETRIEVAL_DOCUMENT; queries need the paired type.
# Not a setting, because it is not stored in the .idx header.  Other
# providers ignore it.
QUERY_TASK_TYPE = "RETRIEVAL_QUERY"


@lru_cache(maxsize=256)
def embed_query(text: str) -> tuple[float, ...] | None:
    """Embed a question in the same space as the book.  Cached on the text.

    Args:
        text: The question.

    Returns:
        The vector, or None without the embedding provider's API key (search
        is then lexical only).

    Raises:
        Exception: Any provider error, e.g. a rejected key, a spent quota or
            an unreachable Ollama.
    """
    settings = get_settings().embedding
    if settings.missing_key():
        return None
    asked = settings.model_copy(update={"task_type": QUERY_TASK_TYPE})
    return tuple(embeddings.embed([text], asked)[0])


_VECTOR = f"""
CALL db.index.vector.queryNodes('{VECTOR_NAME}', $limit, $vector)
YIELD node, score
RETURN node.id AS id, node.heading AS heading, node.entity_type AS entity_type,
       node.content AS content, node.page_start AS page_start,
       node.char_start AS char_start, node.char_end AS char_end,
       labels(node) AS labels, score
"""

_VECTOR_TYPED = _VECTOR.replace(
    "YIELD node, score",
    "YIELD node, score\nWITH node, score WHERE node.entity_type IN $types",
)


def vector_search(text: str, limit: int = 8,
                  types: list[str] | None = None) -> list[Passage]:
    """Nearest sections to the question in ``srd_vector``.

    Args:
        text: The question.
        limit: Maximum passages.
        types: Restrict to these ``entity_type`` values; filtered after the
            index, like ``search``.

    Returns:
        Passages by similarity; empty for a blank question or no API key.

    Raises:
        Exception: Any embedding API error.
    """
    asked = text.strip()
    if not asked:
        return []
    vector = embed_query(asked)
    if vector is None:
        return []
    values = list(vector)
    if types:
        rows = query(_VECTOR_TYPED,
                     {"vector": values, "limit": limit * 5, "types": types})
        rows = rows[:limit]
    else:
        rows = query(_VECTOR, {"vector": values, "limit": limit})
    return [Passage.from_row(row) for row in rows]


# --------------------------------------------------------------------------
# The fusion

# Reciprocal rank fusion's constant, as in Cormack et al. (2009).
RRF_K = 60


def fuse(rankings: dict[str, list[Passage]], limit: int) -> list[Passage]:
    """Reciprocal rank fusion of several rankings.

    Ranks, not scores: BM25 is unbounded and cosine is in [-1, 1].

    Args:
        rankings: Arm name to its ranked passages.
        limit: Maximum passages returned.

    Returns:
        Passages by fused score (ties by section id), with ``score`` set to
        the fused score and ``found_by`` to the arms that returned them.
    """
    scores: dict[str, float] = {}
    found: dict[str, list[str]] = {}
    passages: dict[str, Passage] = {}

    for arm, ranking in rankings.items():
        for rank, passage in enumerate(ranking, start=1):
            key = passage.section_id
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            found.setdefault(key, []).append(arm)
            # Copies differ only in score, which is replaced below.
            passages.setdefault(key, passage)

    ordered = sorted(scores, key=lambda key: (-scores[key], key))
    fused = []
    for key in ordered[:limit]:
        passage = passages[key]
        passage.score = scores[key]
        passage.found_by = found[key]
        fused.append(passage)
    return fused


def hybrid_search(text: str, limit: int = 3, types: list[str] | None = None,
                  candidates: int = 8) -> list[Passage]:
    """Lexical and dense search, fused.

    Args:
        text: The question.
        limit: Passages returned after fusion.
        types: Restrict to these ``entity_type`` values.
        candidates: Passages requested from each arm.

    Returns:
        Up to ``limit`` fused passages.

    Raises:
        Exception: Any embedding API error.
    """
    return fuse({"lexical": search(text, limit=candidates, types=types),
                 "semantic": vector_search(text, limit=candidates, types=types)},
                limit)


_SECTION = """
MATCH (n:Section {id: $id})
CALL (n) {
  OPTIONAL MATCH path = (root:Section)-[:HAS_SUBSECTION*]->(n)
  WHERE NOT ()-[:HAS_SUBSECTION]->(root)
  RETURN coalesce([a IN nodes(path)[..-1] | {id: a.id, heading: a.heading}],
                  []) AS ancestors
}
OPTIONAL MATCH (parent:Section)-[:HAS_SUBSECTION]->(n)
OPTIONAL MATCH (n)-[:HAS_SUBSECTION]->(child:Section)
RETURN n.id AS id, n.heading AS heading, n.entity_type AS entity_type,
       n.content AS content, n.page_start AS page_start,
       n.char_start AS char_start, n.char_end AS char_end, labels(n) AS labels,
       parent.id AS parent_id, parent.heading AS parent_heading, ancestors,
       collect(DISTINCT {id: child.id, heading: child.heading,
                         char_start: child.char_start}) AS children
"""


def get_section(section_id: str) -> tuple[Passage, dict] | None:
    """One section by dotted id, with its place in the tree.

    Args:
        section_id: e.g. ``"11.2.114"``.

    Returns:
        ``(passage, {"ancestors", "parent", "children"})``, or None if no
        such section.  ``ancestors`` runs from the top-level section down to
        the parent, and is empty for a top-level section.  ``children`` are
        in book order and carry ``char_start``.
    """
    rows = query(_SECTION, {"id": section_id})
    if not rows:
        return None
    row = rows[0]
    context = {
        "ancestors": row["ancestors"],
        "parent": ({"id": row["parent_id"], "heading": row["parent_heading"]}
                   if row["parent_id"] else None),
        # collect() over an unmatched OPTIONAL MATCH yields one all-null map.
        "children": sorted((c for c in row["children"] if c["id"]),
                           key=lambda c: c["char_start"] or 0),
    }
    return Passage.from_row(row), context
