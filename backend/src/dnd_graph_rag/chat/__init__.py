"""
Stage 3: rules questions answered from the graph, with citations.

``retrieval`` queries the database, ``tools`` exposes the part of it the
agent may call, ``agent`` is the LangGraph loop, and ``service`` turns one
turn into the event stream the UI renders.
"""

from .service import history, stream_turn, threads

__all__ = ["history", "stream_turn", "threads"]
