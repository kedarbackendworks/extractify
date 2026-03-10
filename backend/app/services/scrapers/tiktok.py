"""
TikTok scraper – yt-dlp is excellent for TikTok.
"""

import re
from typing import Optional

from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.utils.ytdlp_helper import extract_with_ytdlp


class TikTokScraper(BaseScraper):
    platform = "tiktok"

    _DOMAIN_RE = re.compile(r"tiktok\.com")

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        info = await extract_with_ytdlp(url)
        variants = []
        for fmt in info.get("formats", []):
            if not fmt.get("url"):
                continue
            if fmt.get("ext") in ("mhtml",):
                continue
            protocol = fmt.get("protocol", "")
            if protocol not in ("https", "http", ""):
                continue
            has_video = fmt.get("vcodec") != "none"
            has_audio = fmt.get("acodec") != "none"
            height = fmt.get("height")
            if has_video and has_audio:
                label = f"{height}p" if height else fmt.get("format_note", "original")
            elif has_audio and not has_video:
                label = f"audio-{fmt.get('ext', 'webm')}"
            elif has_video:
                label = f"{height}p (video only)" if height else fmt.get("format_note", "original")
            else:
                continue
            variants.append(ScrapedVariant(
                label=label,
                format=fmt.get("ext", "mp4"),
                url=fmt["url"],
                quality=fmt.get("format_note"),
                file_size_bytes=fmt.get("filesize") or fmt.get("filesize_approx"),
                has_video=has_video,
                has_audio=has_audio,
            ))

        return ScrapedResult(
            title=info.get("title"),
            description=info.get("description"),
            author=info.get("uploader") or info.get("creator"),
            thumbnail_url=info.get("thumbnail"),
            duration_seconds=info.get("duration"),
            content_type="short",
            variants=variants,
        )
