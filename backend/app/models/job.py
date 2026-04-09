"""
Job document – tracks every extraction request.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List

from beanie import Document
from pydantic import BaseModel, Field, HttpUrl
from pymongo import ASCENDING, DESCENDING, IndexModel


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ContentType(str, Enum):
    VIDEO = "video"
    IMAGE = "image"
    AUDIO = "audio"
    PDF = "pdf"
    DOCUMENT = "document"
    PRESENTATION = "presentation"
    STORY = "story"
    REEL = "reel"
    SHORT = "short"
    TEXT = "text"
    OTHER = "other"


class DownloadVariant(BaseModel):
    """One downloadable variant (e.g. 720p, 1080p, audio-only)."""
    label: str                              # "1080p", "720p", "audio"
    format: str                             # "mp4", "mp3", "pdf"
    quality: Optional[str] = None           # "HD", "SD", etc.
    file_size_bytes: Optional[int] = None
    download_url: Optional[str] = None      # pre-signed S3 URL
    has_video: Optional[bool] = None
    has_audio: Optional[bool] = None


class ExtractedContent(BaseModel):
    """Metadata about the extracted content."""
    title: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    page_count: Optional[int] = None        # for PDFs / presentations
    content_type: ContentType = ContentType.OTHER
    variants: List[DownloadVariant] = []


class Job(Document):
    """
    Root document stored in MongoDB.
    One Job = one user extraction request.
    """
    url: str                                       # original URL submitted
    platform: str                                  # "instagram", "scribd", …
    content_category: str = "social"               # "social" | "document"
    tab: Optional[str] = None                      # e.g. "Reels", "PDFs"
    status: JobStatus = JobStatus.PENDING
    error_message: Optional[str] = None

    extracted: Optional[ExtractedContent] = None

    # ── Tracking ─────────────────────────────────────
    user_id: Optional[str] = None                  # ObjectId ref (optional)
    ip_address: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "jobs"                               # MongoDB collection name
        use_state_management = True
        indexes = [
            # Recent jobs by platform (platform filter + newest first)
            IndexModel([("platform", ASCENDING), ("created_at", DESCENDING)]),
            # Recent jobs by user; partial index avoids bloating on null user_id rows
            IndexModel(
                [("user_id", ASCENDING), ("created_at", DESCENDING)],
                partialFilterExpression={"user_id": {"$type": "string"}},
            ),
            # Global newest jobs / time-window queries
            IndexModel([("created_at", DESCENDING)]),
        ]

    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://www.instagram.com/reel/xyz",
                "platform": "instagram",
                "content_category": "social",
                "tab": "Reels",
                "status": "pending",
            }
        }
