"""
Read queries against the graph: search, and one section by id.

Search has two arms.  ``search`` is the full-text index, which is Lucene, so
its ranking *is* BM25; ``vector_search`` is the ``srd_vector`` index over the
embeddings stage 2 writes.  ``hybrid_search`` runs both and fuses them, and is
what the agent's ``search_srd`` tool calls.

Everything here returns a :class:`Passage`, which carries the section id and
character range that resolve a citation back to ``srd_hierarchy.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from neo4j import Driver, GraphDatabase

from ..config import get_settings
from ..graph import embeddings
from ..graph.schema import FULLTEXT_NAME, VECTOR_NAME

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
    # Which arms of the hybrid search returned this passage.  Not shown to
    # the model — it is retrieval plumbing — but it is the difference
    # between a fused ranking one can inspect and one that must be taken
    # on faith.
    found_by: list[str] = field(default_factory=list)

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


# --------------------------------------------------------------------------
# The dense arm


# The document side embeds under ``RETRIEVAL_DOCUMENT``; a query is not a
# document, and the model is trained to place the two differently.  It is a
# constant rather than a setting because, unlike everything on
# ``EmbeddingSettings``, it is not baked into the ``.idx`` header: nothing
# about it can drift out of step with a file on disk.
QUERY_TASK_TYPE = "RETRIEVAL_QUERY"


@lru_cache(maxsize=256)
def embed_query(text: str) -> tuple[float, ...] | None:
    """
    One query, embedded in the space the book was embedded in.

    ``None`` without a key, which is the one degradation this module makes:
    the shared ``srd_embeddings.idx`` covers every section of the book but
    cannot cover a question nobody has asked yet, so a checkout with no key
    searches lexically and says nothing about it.  Anything else that goes
    wrong — a rejected key, a spent quota — is raised, and reaches the reader
    through ``service._explain`` like any other failure.

    Cached on the text: a follow-up turn routinely repeats a query, and the
    tuple is what makes the result hashable to begin with.
    """
    settings = get_settings().embedding
    if settings.google_api_key is None:
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
    """
    Nearest neighbours of the question, over the vectors stage 2 loaded.

    Empty without a key rather than an error: ``hybrid_search`` is then the
    lexical arm alone, which is a narrower search and still a working one.

    Filtering happens after the index for the reason it does in ``search``:
    only the index ranks, so the limit is raised and the surplus discarded.
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

# Reciprocal rank fusion's damping constant, at the value the paper uses.  It
# is a constant rather than a setting because nothing here is tuning it.
RRF_K = 60


def fuse(rankings: dict[str, list[Passage]], limit: int) -> list[Passage]:
    """
    Several rankings of the same book, folded into one.

    By *rank*, not by score.  A Lucene BM25 score and a cosine similarity are
    not on the same scale — one is unbounded and corpus-relative, the other
    lives in [-1, 1] — so normalising them against each other would be a
    fiction that ranks whichever arm happens to have the wider spread.  A
    reciprocal rank sum asks each arm only what it can actually answer: which
    of these did you like better.

    Pure, so the arithmetic is tested without a database, the way
    ``neighbourhood.assemble`` is.  ``found_by`` names the arms that returned
    each passage, in the order they were given.
    """
    scores: dict[str, float] = {}
    found: dict[str, list[str]] = {}
    passages: dict[str, Passage] = {}

    for arm, ranking in rankings.items():
        for rank, passage in enumerate(ranking, start=1):
            key = passage.section_id
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            found.setdefault(key, []).append(arm)
            # The first arm to return a passage owns the copy: they differ
            # only in the score the index gave it, which the fused score
            # replaces anyway.
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
    """
    The search the agent actually calls: keywords and meaning at once.

    The two arms fail differently, which is the whole argument for running
    both.  Lucene cannot match a question that shares no words with the book —
    "knocked down" finds nothing about Prone — and the vector index cannot be
    trusted on an exact term, since "Fire damage" and "Cold damage" sit next
    to each other in the space.  Each arm is asked for *candidates*; the
    fusion cuts the union to *limit*.
    """
    return fuse({"lexical": search(text, limit=candidates, types=types),
                 "semantic": vector_search(text, limit=candidates, types=types)},
                limit)


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
