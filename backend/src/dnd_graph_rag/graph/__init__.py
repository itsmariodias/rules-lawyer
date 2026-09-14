"""
Stage 2: the stage 1 artifact loaded into Neo4j.

The stages meet at the JSON on disk and nowhere else.  ``build_graph`` maps,
loads and verifies in one call; the CLI and the API both go through it.
"""

from .mapping import build as map_document
from .pipeline import build_graph
from .verify import verify

__all__ = ["build_graph", "map_document", "verify"]
