"""
File-serve route – serves locally-generated files (e.g. assembled PDFs).

GET /api/files/{filename}

Only serves files from the controlled temp directory to prevent arbitrary
file-system access.
"""

import re
import structlog
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services.scrapers.scribd import PDF_DIR

logger = structlog.get_logger()

router = APIRouter(prefix="/api", tags=["files"])

# Only allow safe filenames: alphanumeric, hyphens, underscores, dots
_SAFE_FILENAME = re.compile(r"^[\w\-]+\.[\w]+$")


@router.get("/files/{filename}")
async def serve_generated_file(filename: str):
    """Serve a locally generated file (PDF, etc.) from the temp directory."""

    if not _SAFE_FILENAME.match(filename):
        raise HTTPException(400, "Invalid filename.")

    file_path = PDF_DIR / filename

    # Security: ensure the resolved path is inside the allowed directory
    try:
        file_path = file_path.resolve()
        PDF_DIR.resolve()
        if not str(file_path).startswith(str(PDF_DIR.resolve())):
            raise HTTPException(403, "Access denied.")
    except Exception:
        raise HTTPException(403, "Access denied.")

    if not file_path.is_file():
        raise HTTPException(404, "File not found. It may have been cleaned up.")

    # Determine media type from extension
    ext = file_path.suffix.lower()
    media_types = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".txt": "text/plain; charset=utf-8",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    # Use a friendly download name
    download_name = filename
    if filename.startswith("scribd_"):
        # Turn "scribd_475008981_abc12345.pdf" into "scribd_document.pdf"
        download_name = "scribd_document.pdf"
    elif filename.startswith("slideshare_"):
        download_name = "slideshare_presentation.pdf"
    elif filename.startswith("calameo_"):
        download_name = "calameo_document.pdf"
    elif filename.startswith("yumpu_"):
        download_name = "yumpu_document.pdf"
    elif filename.startswith("threads_text_"):
        download_name = "threads_post.txt"

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=download_name,
        headers={
            "Content-Disposition": f'inline; filename="{download_name}"',
            "Cache-Control": "public, max-age=3600",
        },
    )
