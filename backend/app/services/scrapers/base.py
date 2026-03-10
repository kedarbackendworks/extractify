"""
Base scraper interface – every platform scraper inherits from this.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ScrapedVariant:
    """One downloadable variant returned by a scraper."""
    label: str                              # "1080p", "audio", "original"
    format: str                             # "mp4", "jpg", "pdf"
    url: str                                # direct download URL
    quality: Optional[str] = None
    file_size_bytes: Optional[int] = None
    has_video: Optional[bool] = None
    has_audio: Optional[bool] = None


@dataclass
class ScrapedResult:
    """Unified result returned by every platform scraper."""
    title: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    page_count: Optional[int] = None
    content_type: str = "other"             # maps to ContentType enum
    variants: List[ScrapedVariant] = field(default_factory=list)


class BaseScraper(ABC):
    """Every platform scraper must implement `scrape`."""

    @property
    @abstractmethod
    def platform(self) -> str:
        """Return the platform slug, e.g. 'instagram'."""

    @abstractmethod
    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        """
        Given a URL (and an optional content-type tab like "Reels"),
        return a ScrapedResult with metadata + download variants.
        """

    def supports(self, url: str) -> bool:
        """Quick check whether this scraper can handle the URL."""
        return False
