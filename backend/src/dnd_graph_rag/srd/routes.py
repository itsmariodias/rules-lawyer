"""Stage 1 over HTTP: ``/health``, ``/parse`` and the source ``/pdf``."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..config import get_settings, markdown_path_for
from . import pipeline

router = APIRouter(tags=["srd"])


class Health(BaseModel):
    status: str
    pdf: str
    pdf_present: bool
    output: str
    output_present: bool


class ParseRequest(BaseModel):
    pdf: Path | None = None
    out: Path | None = None


@router.get("/health", response_model=Health)
def health() -> Health:
    settings = get_settings()
    return Health(
        status="ok",
        pdf=str(settings.pdf_path),
        pdf_present=settings.pdf_path.exists(),
        output=str(settings.output_path),
        output_present=settings.output_path.exists(),
    )


@router.post("/parse")
async def parse(request: ParseRequest | None = None) -> dict:
    """
    Run the pipeline, writing the same JSON and markdown ``srd-parse`` writes.

    Returns the metadata, the validation report and the paths written; the
    document itself is several megabytes and is meant to be read from disk.
    Parsing takes about half a minute, hence the worker thread.
    """
    request = request or ParseRequest()
    out_path = request.out or get_settings().output_path
    try:
        document = await run_in_threadpool(pipeline.build, request.pdf, out_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "meta": document["meta"],
        "validation": document["validation"],
        "written": {
            "json": str(out_path),
            "markdown": str(markdown_path_for(out_path)),
        },
    }


@router.get("/pdf")
async def pdf() -> FileResponse:
    """
    The source PDF, for the facsimile the chat shows beside a citation.

    Served whole rather than per page: pdf.js requests byte ranges, which
    ``FileResponse`` honours, so the browser pulls only the pages it renders.
    """
    path = get_settings().pdf_path
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"PDF not found: {path}")
    return FileResponse(
        path,
        media_type="application/pdf",
        # The one checked-in input, so it never changes; without this the
        # browser refetches 5.8 MB per citation.
        headers={"Cache-Control": "public, max-age=86400"},
    )
