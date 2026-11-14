"""Constraints, indexes and the graph reset.  Every statement is idempotent.

Each uniqueness constraint is also the index the loader's ``MERGE`` uses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from neo4j import Session

# Must match the keys ``mapping`` merges on, plus the names edges match
# folded records by (``(:Class {name})`` is a section).
NODE_KEYS = [
    ("Section", "id"),
    ("CreatureAbility", "key"),
    ("GlossaryTerm", "name"),
    ("Equipment", "name"),
    ("Class", "name"),
    ("ClassLevel", "key"),
    ("Species", "name"),
    ("Background", "name"),
    ("Feat", "name"),
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
    """The vector index statement.

    ``IF NOT EXISTS`` would keep an index of another width, so
    ``apply_schema`` drops one first (see ``drop_stale_vector_index``).

    Args:
        dimensions: Vector width.

    Returns:
        A ``CREATE VECTOR INDEX`` statement.
    """
    return (f"CREATE VECTOR INDEX {VECTOR_NAME} IF NOT EXISTS "
            "FOR (n:Section) ON (n.embedding) OPTIONS {indexConfig: {"
            f"`vector.dimensions`: {dimensions}, "
            "`vector.similarity_function`: 'cosine'}}")


_VECTOR_WIDTH = """
SHOW VECTOR INDEXES YIELD name, options
WHERE name = $name
RETURN options.indexConfig['vector.dimensions'] AS dimensions
"""


def vector_index_width(session: Session) -> int | None:
    """The width ``srd_vector`` was created with.

    Args:
        session: An open session.

    Returns:
        Its configured dimensions, or None if the index does not exist.
    """
    row = session.run(_VECTOR_WIDTH, name=VECTOR_NAME).single()
    return None if row is None else row["dimensions"]


def drop_stale_vector_index(session: Session, dimensions: int) -> bool:
    """Drop ``srd_vector`` if it was created with a different width.

    An index of the wrong width accepts the writes and indexes none of them,
    so the dense search returns nothing without any error.

    Args:
        session: An open session.
        dimensions: The width the vectors about to be written have.

    Returns:
        Whether an index was dropped.
    """
    width = vector_index_width(session)
    if width is None or width == dimensions:
        return False
    session.run(f"DROP INDEX {VECTOR_NAME}")
    return True


def constraint_name(label: str, prop: str) -> str:
    """The name ``constraint_statements`` gives a key's constraint.

    Args:
        label: The node label.
        prop: The key property.

    Returns:
        ``<label>_<prop>_unique``, the label lowercased.
    """
    return f"{label.lower()}_{prop}_unique"


def constraint_statements() -> list[str]:
    """A uniqueness constraint per ``NODE_KEYS`` entry.

    Returns:
        ``CREATE CONSTRAINT ... IF NOT EXISTS`` statements.
    """
    return [
        f"CREATE CONSTRAINT {constraint_name(label, prop)} IF NOT EXISTS "
        f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        for label, prop in NODE_KEYS
    ]


def drop_stale_constraints(session: Session) -> list[str]:
    """Drop uniqueness constraints for keys no longer in ``NODE_KEYS``.

    ``reset`` deletes nodes, not schema, so a key the mapper stopped merging
    on (``Trait.key``) would otherwise be constrained forever.

    Args:
        session: An open session.

    Returns:
        The names dropped.
    """
    wanted = {constraint_name(label, prop) for label, prop in NODE_KEYS}
    found = [row["name"] for row in session.run(
        "SHOW CONSTRAINTS YIELD name, type "
        "WHERE type = 'UNIQUENESS' RETURN name").data()]
    stale = [name for name in found
             if name.endswith("_unique") and name not in wanted]
    for name in stale:
        session.run(f"DROP CONSTRAINT {name} IF EXISTS")
    return stale


def index_statements(dimensions: int) -> list[str]:
    """The ``INDEXES``, the full-text index and the vector index.

    Args:
        dimensions: Width of the vector index.

    Returns:
        ``CREATE ... INDEX ... IF NOT EXISTS`` statements.
    """
    return [
        f"CREATE INDEX {label.lower()}_{prop}_index IF NOT EXISTS "
        f"FOR (n:{label}) ON (n.{prop})"
        for label, prop in INDEXES
    ] + [FULLTEXT, vector_statement(dimensions)]


def apply_schema(session: Session, *, dimensions: int) -> int:
    """Create every constraint and index, then wait up to 300s for them.

    A vector index of another width is dropped and recreated, and a
    constraint on a key no longer merged on is dropped.

    Args:
        session: An open session.
        dimensions: Width of the vector index.

    Returns:
        The number of create statements run.
    """
    drop_stale_vector_index(session, dimensions)
    drop_stale_constraints(session)
    statements = constraint_statements() + index_statements(dimensions)
    for statement in statements:
        session.run(statement)
    session.run("CALL db.awaitIndexes(300)")
    return len(statements)


def reset(session: Session, batch_size: int = 10_000) -> int:
    """Delete every node and relationship, ``batch_size`` nodes per transaction.

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
