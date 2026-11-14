"""The ``rules-lawyer`` command: parse the SRD, embed it, load it into the graph.

    uv run rules-lawyer parse                   PDF -> JSON, markdown and page anchors
    uv run rules-lawyer embed                   JSON -> srd_embeddings.idx (needs a key)
    uv run rules-lawyer load                    JSON and vectors -> Neo4j, verified

Each exits non-zero on failure: ``parse`` when the book disagrees with itself
other than in its known quirks, ``load`` when verification fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rules_lawyer.config import get_settings, markdown_path_for
from rules_lawyer.graph.embeddings import BadEmbeddingsFile, MissingEmbeddings
from rules_lawyer.graph.pipeline import build_embeddings, build_graph
from rules_lawyer.srd.artifact import build, write
from rules_lawyer.srd.verify import KNOWN

# Reported as a message, without a traceback.
FAILURES = (FileNotFoundError, MissingEmbeddings, BadEmbeddingsFile)


def main(argv: list[str] | None = None) -> None:
    """Run one subcommand.

    Args:
        argv: The arguments after the program name; the command line if None.
    """
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="rules-lawyer", description="Parse, embed and load the D&D 5e SRD.")
    commands = parser.add_subparsers(dest="command", required=True)

    parse = commands.add_parser("parse", help="the SRD PDF to srd_hierarchy.json, its markdown and anchors")
    parse.add_argument("--pdf", type=Path, default=settings.pdf_path, help="the SRD PDF")
    parse.add_argument("--out", type=Path, default=settings.output_path,
                       help="the JSON to write; the markdown and anchors go beside it")

    embed = commands.add_parser("embed", help="the artifact's sections to srd_embeddings.idx")
    embed.add_argument("--input", type=Path, default=settings.output_path, help="the srd_hierarchy.json to embed")
    embed.add_argument("--out", type=Path, default=None,
                       help="where to write the file, overriding RULES_LAWYER_EMBEDDINGS")
    embed.add_argument("--refresh", action="store_true", help="ignore any existing file and re-embed everything")

    load = commands.add_parser("load", help="the artifact and its vectors into Neo4j, then verify")
    load.add_argument("--input", type=Path, default=settings.output_path, help="the srd_hierarchy.json to load")
    load.add_argument("--no-reset", dest="reset", action="store_false",
                      help="merge into the existing graph instead of emptying it first")
    load.add_argument("--skip-verify", action="store_true", help="load without checking the result")
    load.add_argument("--embeddings", type=Path, default=None,
                      help="the srd_embeddings.idx to load vectors from, overriding RULES_LAWYER_EMBEDDINGS")
    load.add_argument("--refresh-embeddings", action="store_true",
                      help="ignore the cached file and re-embed everything")

    args = parser.parse_args(argv)
    try:
        {"parse": run_parse, "embed": run_embed, "load": run_load}[args.command](args)
    except FAILURES as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)


def run_parse(args: argparse.Namespace) -> None:
    """Build and write the artifact; report every way the book disagrees with itself.

    Args:
        args: ``pdf`` and ``out`` from the command line.

    Raises:
        FileNotFoundError: The PDF does not exist.
        SystemExit: The book disagrees with itself other than in its known quirks.
    """
    if not args.pdf.exists():
        raise FileNotFoundError(f"PDF not found: {args.pdf}")
    artifact = build(args.pdf, markdown_path_for(args.out).name)
    for path in write(artifact, args.out):
        print(path)
    for message in artifact.problems:
        print(f"known quirk: {message}" if message in KNOWN else message)
    if set(artifact.problems) - KNOWN:
        sys.exit(1)
    print("The book agrees with itself, but for its known quirks.")


def run_embed(args: argparse.Namespace) -> None:
    """Write ``srd_embeddings.idx`` without touching the database.

    Args:
        args: ``input``, ``out`` and ``refresh`` from the command line.
    """
    result = build_embeddings(args.input, embeddings_path=args.out, refresh=args.refresh, report=print)
    print(f"\n{result['count']} embeddings, {result['model']} at {result['dimensions']} dimensions "
          f"({result['task_type']})")
    print(result["output"])


def run_load(args: argparse.Namespace) -> None:
    """Load and verify the graph.

    Args:
        args: ``input``, ``reset``, ``skip_verify``, ``embeddings`` and
            ``refresh_embeddings`` from the command line.

    Raises:
        SystemExit: Verification failed.
    """
    result = build_graph(args.input, reset=args.reset, skip_verify=args.skip_verify,
                         embeddings_path=args.embeddings, refresh_embeddings=args.refresh_embeddings, report=print)
    validation = result["validation"]
    if validation.get("skipped"):
        print("validation skipped")
        return
    print(f"\n{validation['checks']} checks, {len(validation['failures'])} failed")
    if not validation["ok"]:
        print(json.dumps(validation["failures"], indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    print(f"graph: {validation['nodes']} nodes, {validation['relationships']} relationships")


if __name__ == "__main__":
    main()
