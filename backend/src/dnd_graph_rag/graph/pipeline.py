"""Stage 2 orchestration: artifact -> batches -> Neo4j -> verification."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from dnd_graph_rag.config import get_settings
from dnd_graph_rag.graph import embeddings, mapping
from dnd_graph_rag.graph import verify as verification
from dnd_graph_rag.graph.loader import load_graph, session
from dnd_graph_rag.srd.artifact import load

Report = Callable[[str], None]


def build_graph(input_path: Path | None = None, *, reset: bool = True,
                skip_verify: bool = False,
                embeddings_path: Path | None = None,
                refresh_embeddings: bool = False,
                report: Report = lambda _: None) -> dict:
    """
    Load the artifact and its vectors into the configured Neo4j database.

    Args:
        input_path: Defaults to ``settings.output_path``.
        reset: Delete the existing graph first.
        skip_verify: Skip ``verify``; ``validation.ok`` is then None.
        embeddings_path: Defaults to ``settings.embeddings_path``.
        refresh_embeddings: Re-embed every section.
        report: Receives progress lines.

    Returns:
        ``load_graph``'s report, plus ``validation`` and ``input``.

    Raises:
        FileNotFoundError: The artifact does not exist.
        MissingEmbeddings: Vectors are incomplete and there is no key.
        BadEmbeddingsFile: The ``.idx`` cannot be read.
    """
    settings = get_settings()
    input_path = input_path or settings.output_path
    report(f"reading {input_path}")
    document = load(input_path)

    data = mapping.build(document)
    report(f"mapped {data.node_count} nodes and {data.edge_count} relationships")
    for warning in data.warnings:
        report(f"WARNING: {warning}")

    # Before opening a session, so a failure leaves the old graph unreset.
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
    Generate or update the ``.idx`` file without touching the database.

    Args:
        input_path: Defaults to ``settings.output_path``.
        embeddings_path: Defaults to ``settings.embeddings_path``.
        refresh: Re-embed every section.
        report: Receives progress lines.

    Returns:
        Paths, vector count, model, dimensions and task type.

    Raises:
        FileNotFoundError: The artifact does not exist.
        MissingEmbeddings: Vectors are incomplete and there is no key.
    """
    settings = get_settings()
    input_path = input_path or settings.output_path
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


def counts() -> dict:
    """
    Node counts per label and relationship counts per type.

    Returns:
        ``uri``, ``database``, ``nodes`` and ``relationships``.

    Raises:
        neo4j.exceptions.ServiceUnavailable: The database is unreachable.
    """
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
