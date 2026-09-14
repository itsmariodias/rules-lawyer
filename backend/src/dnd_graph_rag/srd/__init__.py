"""
Stage 1: the SRD PDF to a JSON artifact of typed entities and their edges.

``build`` runs the extraction and writes the result; ``load`` reads back
what an earlier run wrote.
"""

from .pipeline import build, load, parse

__all__ = ["build", "load", "parse"]
