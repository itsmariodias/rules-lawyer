"""
Orchestration: artifact on disk -> mapped batches -> Neo4j -> verification.

``build_graph`` is the whole run; it reports progress through an injected
callable and returns a report rather than the data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..config import get_settings
from ..srd import load
from . import embeddings, mapping, verify as verification
from .loader import load_graph, session

Report = Callable[[str], None]


def build_graph(input_path: Path | None = None, *, reset: bool = True,
                skip_verify: bool = False,
                embeddings_path: Path | None = None,
                refresh_embeddings: bool = False,
                report: Report = lambda _: None) -> dict:
    """
    Load ``srd_hierarchy.json`` into the configured Neo4j database.

    Raises ``FileNotFoundError`` when the artifact has not been generated,
    which is the same failure ``srd-parse`` reports for a missing PDF, and
    ``MissingEmbeddings`` when there are neither vectors on disk nor a key to
    generate them with.
    """
    settings = get_settings()
    input_path = input_path or settings.output_path
    if not input_path.exists():
        raise FileNotFoundError(
            f"artifact not found: {input_path} (run `uv run srd-parse` first)")

    report(f"reading {input_path}")
    document = load(input_path)

    data = mapping.build(document)
    report(f"mapped {data.node_count} nodes and {data.edge_count} relationships")
    for warning in data.warnings:
        report(f"WARNING: {warning}")

    # Resolved before a session is opened, so a missing key or a long
    # generation run never holds a half-loaded database open, and so a
    # failure here leaves the previous graph standing rather than resetting
    # it and then giving up.
    vectors = embeddings.resolve(
        document, path=embeddings_path or settings.embeddings_path,
        settings=settings.embedding, refresh=refresh_embeddings,
        report=report)

    with session(settings.neo4j) as open_session:
        result = load_graph(data, open_session, vectors=vectors, reset=reset,
                            batch_size=settings.neo4j.batch_size,
                            embedding_batch_size=settings.embedding.write_batch,
                            report=report)
        if skip_verify:
            result["validation"] = {"ok": None, "skipped": True}
        else:
            report("verifying")
            result["validation"] = verification.verify(document, data,
                                                       open_session, vectors)

    result["input"] = str(input_path)
    return result


def build_embeddings(input_path: Path | None = None, *,
                     embeddings_path: Path | None = None,
                     refresh: bool = False,
                     report: Report = lambda _: None) -> dict:
    """
    The ``.idx`` on its own, with no database involved.

    This is the one-time run that produces the file a reader without an API
    key is given, which is why it is a command of its own rather than only a
    side effect of loading the graph.
    """
    settings = get_settings()
    input_path = input_path or settings.output_path
    if not input_path.exists():
        raise FileNotFoundError(
            f"artifact not found: {input_path} (run `uv run srd-parse` first)")

    path = embeddings_path or settings.embeddings_path
    document = load(input_path)
    vectors = embeddings.resolve(document, path=path,
                                 settings=settings.embedding, refresh=refresh,
                                 report=report)
    return {
        "input": str(input_path),
        "output": str(path),
        "count": len(vectors),
        "model": vectors.model,
        "dimensions": vectors.dimensions,
        "task_type": vectors.task_type,
    }


def counts(report: Report = lambda _: None) -> dict:
    """Node and relationship totals, for the health endpoint."""
    settings = get_settings()
    with session(settings.neo4j) as open_session:
        labels = open_session.run(
            "MATCH (n) UNWIND labels(n) AS label "
            "RETURN label, count(*) AS total ORDER BY label").data()
        types = open_session.run(
            "MATCH ()-[r]->() "
            "RETURN type(r) AS type, count(*) AS total ORDER BY type").data()
    return {
        "uri": settings.neo4j.uri,
        "database": settings.neo4j.database,
        "nodes": {row["label"]: row["total"] for row in labels},
        "relationships": {row["type"]: row["total"] for row in types},
    }
