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
    """Configured input and output paths, and whether each exists."""
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
    Run the pipeline in a worker thread, writing what ``srd-parse`` writes.

    Args:
        request: Optional ``pdf`` and ``out`` paths overriding the settings.

    Returns:
        ``meta``, ``validation`` and the ``written`` paths.  The document
        itself (several MB) stays on disk.

    Raises:
        HTTPException: 404 if the PDF does not exist.
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
    The source PDF.  ``FileResponse`` honours pdf.js's range requests.

    Raises:
        HTTPException: 404 if the PDF does not exist.
    """
    path = get_settings().pdf_path
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"PDF not found: {path}")
    return FileResponse(
        path,
        media_type="application/pdf",
        # Immutable input; avoids refetching 5.8 MB per citation.
        headers={"Cache-Control": "public, max-age=86400"},
    )
