"""
Constraints and indexes, plus the reset that precedes a full reload.

Every uniqueness constraint doubles as the index the loader's ``MERGE``
needs; without one, merging thousands of nodes degenerates into a scan per
row.  All of them are ``IF NOT EXISTS``, so applying the schema twice is a
no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from neo4j import Session

# (label, property) pairs that identify a node.  These mirror the keys
# ``mapping`` merges on; adding a label there means adding it here.
NODE_KEYS = [
    ("Section", "id"),
    ("CreatureAbility", "key"),
    ("GlossaryTerm", "name"),
    ("Equipment", "name"),
    ("Class", "name"),
    ("Subclass", "key"),
    ("ClassLevel", "key"),
    ("Species", "name"),
    ("Background", "name"),
    ("Feat", "name"),
    ("Trait", "key"),
]

# Secondary indexes for the filters a rules question actually starts from:
# "which CR 5 creatures", "which 3rd-level spells", "which conditions".
INDEXES = [
    ("Section", "entity_type"),
    ("Section", "name"),
    ("Section", "cr"),
    ("Section", "level"),
    ("GlossaryTerm", "term_type"),
    ("Equipment", "kind"),
    ("CreatureAbility", "creature"),
]

# The full-text index stage 3 retrieves through.
FULLTEXT_NAME = "srd_text"
FULLTEXT = (
    f"CREATE FULLTEXT INDEX {FULLTEXT_NAME} IF NOT EXISTS "
    "FOR (n:Section) ON EACH [n.heading, n.content]"
)

# The vector index over the embeddings, beside it.  Cosine because ``embed``
# normalises every vector; over unit vectors cosine and dot product agree, and
# cosine is the one that stays right if a future model does not.
VECTOR_NAME = "srd_vector"


def vector_statement(dimensions: int) -> str:
    """
    The dimension is baked into the index, so changing ``EMBED_DIMENSIONS``
    means dropping it: ``IF NOT EXISTS`` would otherwise keep the old one and
    every write of a vector would then fail against it.
    """
    return (f"CREATE VECTOR INDEX {VECTOR_NAME} IF NOT EXISTS "
            "FOR (n:Section) ON (n.embedding) OPTIONS {indexConfig: {"
            f"`vector.dimensions`: {dimensions}, "
            "`vector.similarity_function`: 'cosine'}}")


def constraint_statements() -> list[str]:
    return [
        f"CREATE CONSTRAINT {label.lower()}_{prop}_unique IF NOT EXISTS "
        f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        for label, prop in NODE_KEYS
    ]


def index_statements(dimensions: int) -> list[str]:
    return [
        f"CREATE INDEX {label.lower()}_{prop}_index IF NOT EXISTS "
        f"FOR (n:{label}) ON (n.{prop})"
        for label, prop in INDEXES
    ] + [FULLTEXT, vector_statement(dimensions)]


def apply_schema(session: "Session", *, dimensions: int) -> int:
    """
    Create every constraint and index.  Safe to run repeatedly.

    ``dimensions`` is required rather than optional because every load now
    carries embeddings: there is no shape of this graph that wants the vector
    index left out.
    """
    statements = constraint_statements() + index_statements(dimensions)
    for statement in statements:
        session.run(statement)
    session.run("CALL db.awaitIndexes(300)")
    return len(statements)


def reset(session: "Session", batch_size: int = 10_000) -> int:
    """
    Empty the graph, in batches so a reload does not build one enormous
    transaction.

    A full reload is the default because the artifact is the whole truth:
    merging alone would leave behind nodes that a re-parse has since dropped.
    """
    deleted = 0
    while True:
        summary = session.run(
            "MATCH (n) WITH n LIMIT $limit DETACH DELETE n",
            limit=batch_size,
        ).consume()
        removed = summary.counters.nodes_deleted
        deleted += removed
        if removed == 0:
            return deleted
