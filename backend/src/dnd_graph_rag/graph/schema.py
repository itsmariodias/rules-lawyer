"""
Constraints, indexes and the graph reset.  Every statement is idempotent.

Each uniqueness constraint is also the index the loader's ``MERGE`` uses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from neo4j import Session

# Must match the keys ``mapping`` merges on.
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

# Common query filters: CR, spell level, term type.
INDEXES = [
    ("Section", "entity_type"),
    ("Section", "name"),
    ("Section", "cr"),
    ("Section", "level"),
    ("GlossaryTerm", "term_type"),
    ("Equipment", "kind"),
    ("CreatureAbility", "creature"),
]

FULLTEXT_NAME = "srd_text"
FULLTEXT = (
    f"CREATE FULLTEXT INDEX {FULLTEXT_NAME} IF NOT EXISTS "
    "FOR (n:Section) ON EACH [n.heading, n.content]"
)

# Cosine; vectors are unit length, so it equals dot product.
VECTOR_NAME = "srd_vector"


def vector_statement(dimensions: int) -> str:
    """
    The vector index statement.

    ``IF NOT EXISTS`` keeps an index of the old width after
    ``EMBED_DIMENSIONS`` changes; drop ``srd_vector`` by hand in that case.

    Args:
        dimensions: Vector width.

    Returns:
        A ``CREATE VECTOR INDEX`` statement.
    """
    return (f"CREATE VECTOR INDEX {VECTOR_NAME} IF NOT EXISTS "
            "FOR (n:Section) ON (n.embedding) OPTIONS {indexConfig: {"
            f"`vector.dimensions`: {dimensions}, "
            "`vector.similarity_function`: 'cosine'}}")


def constraint_statements() -> list[str]:
    """A uniqueness constraint per ``NODE_KEYS`` entry."""
    return [
        f"CREATE CONSTRAINT {label.lower()}_{prop}_unique IF NOT EXISTS "
        f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        for label, prop in NODE_KEYS
    ]


def index_statements(dimensions: int) -> list[str]:
    """The ``INDEXES``, the full-text index and the vector index."""
    return [
        f"CREATE INDEX {label.lower()}_{prop}_index IF NOT EXISTS "
        f"FOR (n:{label}) ON (n.{prop})"
        for label, prop in INDEXES
    ] + [FULLTEXT, vector_statement(dimensions)]


def apply_schema(session: "Session", *, dimensions: int) -> int:
    """
    Create every constraint and index, then wait up to 300s for them.

    Args:
        session: An open session.
        dimensions: Width of the vector index.

    Returns:
        The number of statements run.
    """
    statements = constraint_statements() + index_statements(dimensions)
    for statement in statements:
        session.run(statement)
    session.run("CALL db.awaitIndexes(300)")
    return len(statements)


def reset(session: "Session", batch_size: int = 10_000) -> int:
    """
    Delete every node and relationship, ``batch_size`` nodes per transaction.

    Args:
        session: An open session.
        batch_size: Nodes per ``DETACH DELETE``.

    Returns:
        The number of nodes deleted.
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
