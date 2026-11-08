"""Stage 1: the SRD PDF to a JSON artifact of typed entities and their edges."""

from .pipeline import build, load, parse

__all__ = ["build", "load", "parse"]
