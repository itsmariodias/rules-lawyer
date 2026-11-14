"""The SRD over HTTP: ``/health``, ``/parse`` and the source ``/pdf``."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from rules_lawyer.config import get_settings, markdown_path_for
from rules_lawyer.srd.artifact import build, write

router = APIRouter(tags=["srd"])


class Health(BaseModel):
    """The configured input and output, and whether each exists."""

    status: str
    pdf: str
    pdf_present: bool
    output: str
    output_present: bool


class ParseRequest(BaseModel):
    """Paths overriding the settings for one parse."""

    pdf: Path | None = None
    out: Path | None = None


@router.get("/health", response_model=Health)
def health() -> Health:
    """Configured input and output paths, and whether each exists.

    Returns:
        The paths and whether each file is present.
    """
    settings = get_settings()
    return Health(status="ok", pdf=str(settings.pdf_path), pdf_present=settings.pdf_path.exists(),
                  output=str(settings.output_path), output_present=settings.output_path.exists())


@router.post("/parse")
async def parse(request: ParseRequest | None = None) -> dict:
    """Build and write the artifact in a worker thread, as ``rules-lawyer parse`` does.

    Args:
        request: Optional ``pdf`` and ``out`` paths overriding the settings.

    Returns:
        ``meta``, ``validation`` and the paths ``written``; the document itself
        (several MB) stays on disk.

    Raises:
        HTTPException: 404 if the PDF does not exist.
    """
    request = request or ParseRequest()
    settings = get_settings()
    pdf_path = request.pdf or settings.pdf_path
    out_path = request.out or settings.output_path
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"PDF not found: {pdf_path}")
    artifact = await run_in_threadpool(build, pdf_path, markdown_path_for(out_path).name)
    json_path, markdown_path, anchors_path = await run_in_threadpool(write, artifact, out_path)
    return {"meta": artifact.document["meta"], "validation": artifact.document["validation"],
            "written": {"json": str(json_path), "markdown": str(markdown_path), "anchors": str(anchors_path)}}


@router.get("/pdf")
async def pdf() -> FileResponse:
    """The source PDF; ``FileResponse`` honours pdf.js's range requests.

    Returns:
        The file, cacheable for a day.

    Raises:
        HTTPException: 404 if the PDF does not exist.
    """
    path = get_settings().pdf_path
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"PDF not found: {path}")
    # Immutable input; avoids refetching 5.8 MB per citation.
    return FileResponse(path, media_type="application/pdf", headers={"Cache-Control": "public, max-age=86400"})
