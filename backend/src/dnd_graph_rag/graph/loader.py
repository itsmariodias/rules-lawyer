"""
Write the mapped batches into Neo4j.

``mapping`` has already decided what every node and relationship is, so all
that is left is batching, transactions and progress reporting.  Progress goes
to an injected callable: the CLI passes ``print``, the API passes nothing.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator

from neo4j import Driver, GraphDatabase, Session

from ..config import Neo4jSettings, get_settings
from . import schema
from .embeddings import Vectors
from .model import EdgeBatch, GraphData, NodeBatch

Report = Callable[[str], None]


@contextmanager
def session(settings: Neo4jSettings | None = None) -> Iterator[Session]:
    """A session against the configured database, closed on the way out."""
    settings = settings or get_settings().neo4j
    driver: Driver = GraphDatabase.driver(settings.uri, auth=settings.auth)
    try:
        with driver.session(database=settings.database) as open_session:
            yield open_session
    finally:
        driver.close()


def node_query(batch: NodeBatch) -> str:
    """
    MERGE on the key, then overwrite the properties.

    ``SET n += row`` rather than ``SET n = row`` so a node written by one
    batch and enriched by another — a creature's section, then its stat
    block — keeps both halves.
    """
    labels = "".join(f":{label}" for label in batch.labels)
    return (
        "UNWIND $rows AS row "
        f"MERGE (n:{batch.primary} {{{batch.key}: row.{batch.key}}}) "
        f"SET n{labels} "
        "SET n += row"
    )


def edge_query(batch: EdgeBatch) -> str:
    """
    Both endpoints are MATCHed, never MERGEd.

    An edge whose endpoint is missing is silently skipped here because
    ``mapping`` has already resolved every one of them and reported anything
    it could not; a MERGE would instead invent an empty node and hide it.
    """
    return (
        "UNWIND $rows AS row "
        f"MATCH (a:{batch.start_label} {{{batch.start_key}: row.start}}) "
        f"MATCH (b:{batch.end_label} {{{batch.end_key}: row.end}}) "
        f"MERGE (a)-[r:{batch.type}]->(b) "
        "SET r += row.properties"
    )


# A pass of its own rather than a property folded into the mapped rows, for
# three reasons: ``mapping`` stays a pure function of the document with no
# knowledge of a vector, ``clean()`` does not walk 1536 floats on every
# ``add``, and vectors can be refreshed without reloading the graph.
#
# MATCH, never MERGE, for the reason ``edge_query`` gives: a key with no
# section is a stale file, not a licence to invent a node.
EMBEDDING_QUERY = (
    "UNWIND $rows AS row "
    "MATCH (n:Section {id: row.id}) "
    "SET n.embedding = row.embedding"
)


def _write(open_session: Session, query: str, rows: list[dict],
           batch_size: int) -> int:
    written = 0
    for start in range(0, len(rows), batch_size):
        chunk = rows[start:start + batch_size]
        open_session.execute_write(
            lambda tx, chunk=chunk: tx.run(query, rows=chunk).consume())
        written += len(chunk)
    return written


def write_embeddings(vectors: Vectors, open_session: Session, *,
                     batch_size: int = 200,
                     report: Report = lambda _: None) -> int:
    """
    Set one vector per section, in transactions small enough to be sane.

    Smaller batches than the node loader's, because each row carries 1536
    floats rather than a paragraph.
    """
    rows = [{"id": key, "embedding": row}
            for key, row in zip(vectors.keys, vectors.rows)]
    written = _write(open_session, EMBEDDING_QUERY, rows, batch_size)
    report(f"embeddings: {written}")
    return written


def load_graph(data: GraphData, open_session: Session, *,
               vectors: Vectors, reset: bool = True, batch_size: int = 1000,
               embedding_batch_size: int = 200,
               report: Report = lambda _: None) -> dict:
    """
    Apply the schema, optionally empty the graph, then write every batch.

    Nodes go in before relationships so that every endpoint a relationship
    matches on already exists, and the embeddings go in last, once there is a
    section for each of them to land on.
    """
    statements = schema.apply_schema(open_session,
                                     dimensions=vectors.dimensions)
    report(f"schema: {statements} constraints and indexes")

    if reset:
        deleted = schema.reset(open_session)
        report(f"reset: {deleted} nodes deleted")

    nodes = 0
    for batch in data.nodes:
        nodes += _write(open_session, node_query(batch), batch.rows, batch_size)
        report(f"  {batch.signature}: {len(batch)}")
    report(f"nodes: {nodes}")

    edges = 0
    for batch in data.edges:
        edges += _write(open_session, edge_query(batch), batch.rows, batch_size)
    report(f"relationships: {edges}")

    embedded = write_embeddings(vectors, open_session,
                                batch_size=embedding_batch_size, report=report)

    return {
        "nodes_written": nodes,
        "relationships_written": edges,
        "embeddings_written": embedded,
        "reset": reset,
        "nodes_by_label": data.counts_by_label(),
        "relationships_by_type": data.counts_by_type(),
        "unresolved_references": data.unresolved,
        "warnings": data.warnings,
    }
