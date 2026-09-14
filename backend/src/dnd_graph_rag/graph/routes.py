"""
Stage 2 over HTTP: ``/graph/health`` and ``/graph/load``.

The Neo4j driver is synchronous, so both endpoints use a worker thread.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import pipeline
from .embeddings import BadEmbeddingsFile, MissingEmbeddings

router = APIRouter(prefix="/graph", tags=["graph"])


class GraphLoadRequest(BaseModel):
    input: Path | None = None
    reset: bool = True
    skip_verify: bool = False
    embeddings: Path | None = None
    refresh_embeddings: bool = False


@router.get("/health")
async def graph_health() -> dict:
    """
    Whether the graph is reachable, and what is currently in it.

    Counts are queried rather than remembered from a load, so this answers
    "is the graph loaded?" as well as "is Neo4j up?".
    """
    try:
        return {"status": "ok", **await run_in_threadpool(pipeline.counts)}
    except Exception as exc:  # the driver raises a family of connection errors
        raise HTTPException(status_code=503,
                            detail=f"graph unavailable: {exc}") from exc


@router.post("/load")
async def graph_load(request: GraphLoadRequest | None = None) -> dict:
    """Do what ``srd-graph-load`` does, returning its verification report."""
    request = request or GraphLoadRequest()
    try:
        return await run_in_threadpool(
            lambda: pipeline.build_graph(
                request.input, reset=request.reset,
                skip_verify=request.skip_verify,
                embeddings_path=request.embeddings,
                refresh_embeddings=request.refresh_embeddings)
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (MissingEmbeddings, BadEmbeddingsFile) as exc:
        # 409 rather than 404: the file may well be there, and the problem is
        # that it does not cover this artifact and there is no key to finish
        # it with.  The message names both ways out.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
