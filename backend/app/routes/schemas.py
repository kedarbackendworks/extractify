"""
Pydantic schemas for API request / response validation.
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, HttpUrl


# ── Request ──────────────────────────────────────────

class ExtractRequest(BaseModel):
    """POST /api/extract body."""
    url: str
    platform: Optional[str] = None       # auto-detected if omitted
    tab: Optional[str] = None            # e.g. "Reels", "PDFs"


# ── Response ─────────────────────────────────────────

class VariantOut(BaseModel):
    label: str
    format: str
    quality: Optional[str] = None
    file_size_bytes: Optional[int] = None
    download_url: Optional[str] = None
    has_video: Optional[bool] = None
    has_audio: Optional[bool] = None


class ExtractedContentOut(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    page_count: Optional[int] = None
    content_type: str = "other"
    variants: List[VariantOut] = []


class JobOut(BaseModel):
    id: str
    url: str
    platform: str
    content_category: str
    tab: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    extracted: Optional[ExtractedContentOut] = None
    created_at: datetime
    updated_at: datetime


class HealthOut(BaseModel):
    status: str = "ok"
    mongo: str = "connected"
    version: str = "0.1.0"
