"""Batched ``UNWIND`` writes of mapped batches and vectors into Neo4j."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator

from neo4j import Driver, GraphDatabase, Session

from rules_lawyer.config import Neo4jSettings, get_settings
from rules_lawyer.graph import schema
from rules_lawyer.graph.embeddings import Vectors
from rules_lawyer.graph.model import EdgeBatch, GraphData, NodeBatch

Report = Callable[[str], None]


@contextmanager
def session(settings: Neo4jSettings | None = None) -> Iterator[Session]:
    """
    A session on a driver opened for this call and closed with it.

    Args:
        settings: Defaults to ``get_settings().neo4j``.

    Yields:
        An open session on the configured database.
    """
    settings = settings or get_settings().neo4j
    driver: Driver = GraphDatabase.driver(settings.uri, auth=settings.auth)
    try:
        with driver.session(database=settings.database) as open_session:
            yield open_session
    finally:
        driver.close()


def node_query(batch: NodeBatch) -> str:
    """
    Cypher that MERGEs each row on its key and sets labels and properties.

    ``+=`` so properties from an earlier batch on the same node survive.
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
    Cypher that MATCHes both endpoints and MERGEs the relationship.

    A row with a missing endpoint is skipped silently; ``mapping`` already
    reported it as unresolved.
    """
    return (
        "UNWIND $rows AS row "
        f"MATCH (a:{batch.start_label} {{{batch.start_key}: row.start}}) "
        f"MATCH (b:{batch.end_label} {{{batch.end_key}: row.end}}) "
        f"MERGE (a)-[r:{batch.type}]->(b) "
        "SET r += row.properties"
    )


# Separate from the node rows so ``clean()`` never walks 1536 floats per row.
# MATCH: a key with no section is a stale file and is skipped.
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
    Set ``embedding`` on each section in ``vectors``.

    Args:
        vectors: Vectors keyed by section id.
        open_session: An open session.
        batch_size: Rows per transaction.
        report: Receives a progress line.

    Returns:
        The number of rows sent.
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
    Apply the schema, optionally reset, then write nodes, edges and vectors.

    Args:
        data: Output of ``mapping.build``.
        open_session: An open session.
        vectors: A vector per section; sets the vector index width.
        reset: Delete everything first.
        batch_size: Rows per node or edge transaction.
        embedding_batch_size: Rows per vector transaction.
        report: Receives progress lines.

    Returns:
        Counts written, counts by label and type, unresolved references and
        mapper warnings.
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
