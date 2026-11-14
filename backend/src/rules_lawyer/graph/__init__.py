"""Stage 2: the stage 1 artifact loaded into Neo4j."""

from rules_lawyer.graph.mapping import build as map_document
from rules_lawyer.graph.pipeline import build_graph
from rules_lawyer.graph.verify import verify

__all__ = ["build_graph", "map_document", "verify"]
