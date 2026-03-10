"""
Generic social scraper – covers LinkedIn, Pinterest, Reddit, Tumblr,
Twitch, Vimeo, VK, SoundCloud, Threads via yt-dlp + OG-tag fallback.

Most of these platforms are supported by yt-dlp out of the box.
"""

import re
from typing import Optional

from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.services.scrapers.helpers import build_ytdlp_variants, parse_og_tags
from app.utils.ytdlp_helper import extract_with_ytdlp
from app.utils.browser import get_page_content


class GenericSocialScraper(BaseScraper):
    """
    Catch-all scraper for platforms that yt-dlp already supports:
    Tumblr, Twitch, Vimeo, VK, SoundCloud.

    Platforms with dedicated scrapers (LinkedIn, Pinterest, Reddit, Threads)
    have been moved to their own modules.
    """

    platform = "generic"

    # Map of supported domains  (only platforms WITHOUT dedicated scrapers)
    _SUPPORTED: dict[str, str] = {
        "tumblr.com": "tumblr",
        "twitch.tv": "twitch",
        "vimeo.com": "vimeo",
        "vk.com": "vk",
        "soundcloud.com": "soundcloud",
    }

    def supports(self, url: str) -> bool:
        return any(domain in url for domain in self._SUPPORTED)

    def _detect_platform(self, url: str) -> str:
        for domain, plat in self._SUPPORTED.items():
            if domain in url:
                return plat
        return "generic"

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        detected = self._detect_platform(url)

        # First try yt-dlp (works for most video / audio content)
        try:
            info = await extract_with_ytdlp(url)
            variants = build_ytdlp_variants(info)

            content_type = "video"
            if detected == "soundcloud":
                content_type = "audio"

            if variants:
                return ScrapedResult(
                    title=info.get("title"),
                    description=info.get("description"),
                    author=info.get("uploader") or info.get("channel"),
                    thumbnail_url=info.get("thumbnail"),
                    duration_seconds=info.get("duration"),
                    content_type=content_type,
                    variants=variants,
                )
        except Exception:
            pass

        # Fallback – extract OG meta from the page
        html = await get_page_content(url)
        if html:
            result = parse_og_tags(html, f"{detected.title()} Content", "other")
            if result.variants:
                return result

        raise ValueError(
            f"Could not extract content from {detected.title()}. "
            f"The content may be private or require authentication."
        )
