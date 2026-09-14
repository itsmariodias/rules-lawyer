"""The ``srd-graph-load`` and ``srd-embed`` console scripts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import get_settings
from .embeddings import BadEmbeddingsFile, MissingEmbeddings
from .pipeline import build_embeddings, build_graph

# The two ways a run can be short of vectors, both of which are the reader's
# to fix and neither of which wants a traceback.
_EMBEDDING_FAILURES = (MissingEmbeddings, BadEmbeddingsFile)


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Load the parsed SRD artifact into Neo4j.")
    parser.add_argument("--input", type=Path, default=settings.output_path,
                        help="the srd_hierarchy.json to load")
    parser.add_argument("--no-reset", dest="reset", action="store_false",
                        help="merge into the existing graph instead of "
                             "emptying it first")
    parser.add_argument("--skip-verify", action="store_true",
                        help="load without checking the result")
    parser.add_argument("--embeddings", type=Path, default=None,
                        help="the srd_embeddings.idx to load vectors from, "
                             "overriding DND_GRAPH_RAG_EMBEDDINGS")
    parser.add_argument("--refresh-embeddings", action="store_true",
                        help="ignore the cached file and re-embed everything")
    args = parser.parse_args()

    try:
        result = build_graph(args.input, reset=args.reset,
                             skip_verify=args.skip_verify,
                             embeddings_path=args.embeddings,
                             refresh_embeddings=args.refresh_embeddings,
                             report=print)
    except (FileNotFoundError, *_EMBEDDING_FAILURES) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    validation = result["validation"]
    if validation.get("skipped"):
        print("validation skipped")
        return

    print(f"\n{validation['checks']} checks, "
          f"{len(validation['failures'])} failed")
    if not validation["ok"]:
        print(json.dumps(validation["failures"], indent=2, ensure_ascii=False),
              file=sys.stderr)
        sys.exit(1)
    print(f"graph: {validation['nodes']} nodes, "
          f"{validation['relationships']} relationships")


def embed_main() -> None:
    """
    ``srd-embed``: the one-time run that produces the shareable ``.idx``.

    Separate from the load because it is the only thing in either pipeline
    that needs an API key, and because the file it writes is what lets
    everybody else's load do without one.
    """
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Embed the parsed SRD artifact into srd_embeddings.idx.")
    parser.add_argument("--input", type=Path, default=settings.output_path,
                        help="the srd_hierarchy.json to embed")
    parser.add_argument("--out", type=Path, default=None,
                        help="where to write the file, overriding "
                             "DND_GRAPH_RAG_EMBEDDINGS")
    parser.add_argument("--refresh", action="store_true",
                        help="ignore any existing file and re-embed everything")
    args = parser.parse_args()

    try:
        result = build_embeddings(args.input, embeddings_path=args.out,
                                  refresh=args.refresh, report=print)
    except (FileNotFoundError, *_EMBEDDING_FAILURES) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{result['count']} embeddings, {result['model']} at "
          f"{result['dimensions']} dimensions ({result['task_type']})")
    print(result["output"])
