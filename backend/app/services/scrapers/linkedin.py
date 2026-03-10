"""
LinkedIn scraper – video posts, articles, and document posts.

LinkedIn aggressively blocks anonymous scraping.  Best results:
  1. yt-dlp  (has a LinkedIn extractor for native video posts)
  2. Playwright OG tags  (LinkedIn serves decent OG metadata for public content)
  3. Document-slide image extraction via page parsing
"""

import re
from html import unescape
from typing import Optional

from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.services.scrapers.helpers import build_ytdlp_variants, parse_og_tags
from app.utils.ytdlp_helper import extract_with_ytdlp
from app.utils.browser import get_page_content


class LinkedInScraper(BaseScraper):
    platform = "linkedin"

    _DOMAIN_RE = re.compile(r"linkedin\.com")

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        # ── Strategy 1: yt-dlp for video posts ───────────────────
        if content_tab in ("Video", None) or "/video/" in url:
            try:
                info = await extract_with_ytdlp(url)
                variants = build_ytdlp_variants(info)
                if variants:
                    return ScrapedResult(
                        title=info.get("title"),
                        description=info.get("description"),
                        author=info.get("uploader"),
                        thumbnail_url=info.get("thumbnail"),
                        duration_seconds=info.get("duration"),
                        content_type="video",
                        variants=variants,
                    )
            except Exception:
                pass

        # ── Strategy 2: Playwright page parsing ──────────────────
        html = await get_page_content(url, use_browser=True)
        if html:
            # Document posts embed slide images on LinkedIn CDN
            if content_tab == "Documents" or "/document/" in url:
                doc_images = re.findall(
                    r"(https://media\.licdn\.com/dms/document/[^\s\"']+\.(?:jpg|png|webp))",
                    html,
                )
                if doc_images:
                    seen: set[str] = set()
                    variants: list[ScrapedVariant] = []
                    for img_url in doc_images:
                        clean = unescape(img_url)
                        if clean not in seen:
                            seen.add(clean)
                            variants.append(
                                ScrapedVariant(
                                    label=f"Slide {len(variants) + 1}",
                                    format="jpg",
                                    url=clean,
                                )
                            )
                    if variants:
                        og_result = parse_og_tags(html, "LinkedIn Document", "document")
                        return ScrapedResult(
                            title=og_result.title or "LinkedIn Document",
                            description=og_result.description,
                            thumbnail_url=og_result.thumbnail_url,
                            content_type="document",
                            variants=variants,
                        )

            # Generic OG-tag extraction (works for articles, posts)
            result = parse_og_tags(html, "LinkedIn Post", "other")
            if result.variants:
                return result

            # Try extracting embedded video/image from the rendered page
            video_match = re.search(
                r"(https://[^\s\"']+(?:dms/image|dms/video|licdn)[^\s\"']+\.(?:mp4|jpg|png))",
                html,
            )
            if video_match:
                media_url = unescape(video_match.group(1))
                is_video = media_url.endswith(".mp4")
                return ScrapedResult(
                    title="LinkedIn Content",
                    content_type="video" if is_video else "image",
                    thumbnail_url=None if is_video else media_url,
                    variants=[
                        ScrapedVariant(
                            label="Video" if is_video else "Image",
                            format="mp4" if is_video else "jpg",
                            url=media_url,
                            has_video=is_video,
                            has_audio=is_video,
                        )
                    ],
                )

        raise ValueError(
            "Could not extract this LinkedIn content. "
            "LinkedIn requires authentication for most content."
        )
