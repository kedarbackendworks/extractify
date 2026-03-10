"""
YouTube scraper – yt-dlp is the gold standard here.
"""

import re
from typing import Optional

from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.utils.ytdlp_helper import extract_with_ytdlp


class YouTubeScraper(BaseScraper):
    platform = "youtube"

    _DOMAIN_RE = re.compile(r"(youtube\.com|youtu\.be)")

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        info = await extract_with_ytdlp(url)

        variants: list[ScrapedVariant] = []
        for fmt in info.get("formats", []):
            if not fmt.get("url"):
                continue
            # Skip storyboard / mhtml formats
            if fmt.get("ext") in ("mhtml",):
                continue
            # Skip non-direct protocols (m3u8, DASH manifests, etc.)
            protocol = fmt.get("protocol", "")
            if protocol not in ("https", "http"):
                continue

            height = fmt.get("height")
            has_audio = fmt.get("acodec") != "none"
            has_video = fmt.get("vcodec") != "none"

            # Build descriptive label
            if has_video and has_audio:
                label = f"{height}p" if height else fmt.get("format_note", "unknown")
            elif has_audio and not has_video:
                label = f"audio-{fmt.get('ext', 'webm')}"
            elif has_video and not has_audio:
                label = f"{height}p (video only)" if height else fmt.get("format_note", "unknown")
            else:
                continue  # skip formats with neither

            variants.append(ScrapedVariant(
                label=label,
                format=fmt.get("ext", "mp4"),
                url=fmt["url"],
                quality=fmt.get("format_note"),
                file_size_bytes=fmt.get("filesize") or fmt.get("filesize_approx"),
                has_video=has_video,
                has_audio=has_audio,
            ))

        # Some responses expose a direct URL instead of per-format entries.
        if not variants and info.get("url"):
            variants.append(
                ScrapedVariant(
                    label="source",
                    format=info.get("ext", "mp4"),
                    url=info["url"],
                    quality=None,
                    file_size_bytes=info.get("filesize") or info.get("filesize_approx"),
                    has_video=True,
                    has_audio=True,
                )
            )

        if not variants:
            raise ValueError(
                "No downloadable YouTube streams were returned for this link. "
                "Try again after a minute, or try another video URL."
            )

        content_type = "video"
        if content_tab == "Shorts" or "/shorts/" in url:
            content_type = "short"
        elif content_tab == "Live":
            content_type = "video"

        return ScrapedResult(
            title=info.get("title"),
            description=info.get("description"),
            author=info.get("uploader") or info.get("channel"),
            thumbnail_url=info.get("thumbnail"),
            duration_seconds=info.get("duration"),
            content_type=content_type,
            variants=variants,
        )
