"""
Extraction API routes.

POST /api/extract       → Create a new extraction job (run in background task)
GET  /api/extract/{id}  → Poll job status / get results
GET  /api/platforms      → List supported platforms (mirrors frontend config)
"""

import asyncio
import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlparse

from app.models.job import Job, JobStatus
from app.routes.schemas import ExtractRequest, JobOut, ExtractedContentOut, VariantOut
from app.utils.url_detect import detect_platform
from app.core.database import is_connected

logger = structlog.get_logger()

router = APIRouter(prefix="/api", tags=["extract"])


def _normalize_input_url(raw_url: str) -> str:
    """Decode/unwrap user-provided URL so scrapers receive a clean target URL."""
    cleaned = raw_url.strip()

    # Decode percent-encoding at most twice (common when URLs are re-encoded)
    for _ in range(2):
        decoded = unquote(cleaned)
        if decoded == cleaned:
            break
        cleaned = decoded

    parsed = urlparse(cleaned)

    # If user pasted our own platform page URL, extract the nested `url` query param
    if parsed.path.startswith("/platform/"):
        nested = parse_qs(parsed.query).get("url", [None])[0]
        if nested:
            nested_clean = nested.strip()
            for _ in range(2):
                nested_decoded = unquote(nested_clean)
                if nested_decoded == nested_clean:
                    break
                nested_clean = nested_decoded
            return nested_clean

    return cleaned


# ── Background extraction helper ────────────────────────────────

async def _run_extraction_background(job_id: str) -> None:
    """Run the scraping in the background and update the job in MongoDB."""
    from app.services.scrapers.registry import run_scraper
    from app.models.job import ExtractedContent, DownloadVariant, ContentType

    job = await Job.get(job_id)
    if not job:
        return

    job.status = JobStatus.PROCESSING
    job.updated_at = datetime.utcnow()
    await job.save()

    try:
        result = await run_scraper(platform=job.platform, url=job.url, content_tab=job.tab)

        if not result.variants:
            raise ValueError(
                "No downloadable content found. "
                "The content may be private, deleted, or require authentication."
            )

        variants = [
            DownloadVariant(label=v.label, format=v.format, quality=v.quality,
                            file_size_bytes=v.file_size_bytes, download_url=v.url,
                            has_video=v.has_video, has_audio=v.has_audio)
            for v in result.variants
        ]
        try:
            ct = ContentType(result.content_type)
        except ValueError:
            ct = ContentType.OTHER
        job.extracted = ExtractedContent(
            title=result.title, description=result.description,
            author=result.author, thumbnail_url=result.thumbnail_url,
            duration_seconds=result.duration_seconds,
            page_count=result.page_count, content_type=ct, variants=variants,
        )
        job.status = JobStatus.COMPLETED
        logger.info("extraction_completed", job_id=job_id, platform=job.platform)
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error_message = str(exc)[:500]
        logger.error("extraction_failed", job_id=job_id, error=str(exc)[:200])
    job.updated_at = datetime.utcnow()
    await job.save()


# ── POST /api/extract ───────────────────────────────────────────

@router.post("/extract", response_model=JobOut, status_code=202)
async def create_extraction(body: ExtractRequest, request: Request, background_tasks: BackgroundTasks):
    """
    Accept a URL, detect the platform, persist a Job, and dispatch
    extraction in the background.
    """
    if not is_connected():
        raise HTTPException(503, "Database is not available. Please try again later.")

    url = _normalize_input_url(str(body.url))

    # Detect platform
    platform = body.platform
    category = "social"
    if not platform:
        platform, category = detect_platform(url)
        if not platform:
            raise HTTPException(400, "Could not detect platform from URL. Please provide `platform` explicitly.")
    else:
        _, category = detect_platform(url)
        if category == "unknown":
            category = "social"

    # Create job
    job = Job(
        url=url,
        platform=platform,
        content_category=category,
        tab=body.tab,
        status=JobStatus.PENDING,
        ip_address=request.client.host if request.client else None,
    )
    await job.insert()

    # Dispatch using FastAPI background task (no Redis/Celery needed)
    background_tasks.add_task(_run_extraction_background, str(job.id))

    return _job_to_out(job)


# ── GET /api/extract/{job_id} ───────────────────────────────────

@router.get("/extract/{job_id}", response_model=JobOut)
async def get_extraction(job_id: str):
    """Poll the status of an extraction job."""
    job = await Job.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_to_out(job)


# ── GET /api/platforms ──────────────────────────────────────────

@router.get("/platforms")
async def list_platforms():
    """Return the list of supported platforms (useful for frontend hydration)."""
    from app.utils.url_detect import _PLATFORM_MAP
    platforms = {}
    for domain, (slug, cat) in _PLATFORM_MAP.items():
        if slug not in platforms:
            platforms[slug] = {"slug": slug, "category": cat, "domains": []}
        platforms[slug]["domains"].append(domain)
    return list(platforms.values())


# ── Helpers ─────────────────────────────────────────────────────

def _job_to_out(job: Job) -> JobOut:
    extracted = None
    if job.extracted:
        e = job.extracted
        extracted = ExtractedContentOut(
            title=e.title,
            description=e.description,
            author=e.author,
            thumbnail_url=e.thumbnail_url,
            duration_seconds=e.duration_seconds,
            page_count=e.page_count,
            content_type=e.content_type.value if hasattr(e.content_type, "value") else str(e.content_type),
            variants=[
                VariantOut(
                    label=v.label,
                    format=v.format,
                    quality=v.quality,
                    file_size_bytes=v.file_size_bytes,
                    download_url=v.download_url,
                    has_video=v.has_video,
                    has_audio=v.has_audio,
                )
                for v in (e.variants or [])
            ],
        )
    return JobOut(
        id=str(job.id),
        url=job.url,
        platform=job.platform,
        content_category=job.content_category,
        tab=job.tab,
        status=job.status.value,
        error_message=job.error_message,
        extracted=extracted,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
