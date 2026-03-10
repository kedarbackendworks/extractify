"""
Pinterest scraper – extracts pins (images and video pins).

Strategy:
  1. Parse JSON-LD structured data from pin pages  (contains original image URL)
  2. Parse embedded ``__PWS_DATA__`` JSON for video/image media
  3. Fallback to yt-dlp for video pins
  4. Fallback to Playwright OG tags
"""

import re
import json
from html import unescape
from typing import Optional

import httpx
from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.services.scrapers.helpers import build_ytdlp_variants, parse_og_tags
from app.utils.ytdlp_helper import extract_with_ytdlp
from app.utils.browser import get_page_content


class PinterestScraper(BaseScraper):
    platform = "pinterest"

    _DOMAIN_RE = re.compile(r"(pinterest\.com|pin\.it)")

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        # Resolve short URLs  (pin.it → pinterest.com)
        resolved_url = await self._resolve_url(url)

        # ── Strategy 1: Fetch page and parse structured data ─────
        html = await get_page_content(resolved_url)
        if html:
            result = self._parse_pin_page(html)
            if result and result.variants:
                return result

        # ── Strategy 2: yt-dlp for video pins ────────────────────
        try:
            info = await extract_with_ytdlp(resolved_url)
            variants = build_ytdlp_variants(info)
            if variants:
                return ScrapedResult(
                    title=info.get("title", "Pinterest Video"),
                    description=info.get("description"),
                    author=info.get("uploader"),
                    thumbnail_url=info.get("thumbnail"),
                    duration_seconds=info.get("duration"),
                    content_type="video",
                    variants=variants,
                )
        except Exception:
            pass

        # ── Strategy 3: OG-tag fallback ──────────────────────────
        if html:
            result = parse_og_tags(html, "Pinterest Pin", "image")
            if result.variants:
                return result

        raise ValueError("Could not extract this Pinterest pin.")

    # ── Private helpers ──────────────────────────────────────────

    async def _resolve_url(self, url: str) -> str:
        """Resolve pin.it short URLs to full pinterest.com URLs."""
        if "pin.it" not in url:
            return url
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                resp = await client.head(url)
                return str(resp.url)
        except Exception:
            return url

    @staticmethod
    def _parse_pin_page(html: str) -> Optional[ScrapedResult]:
        """Extract pin media from JSON-LD or embedded page data."""
        variants: list[ScrapedVariant] = []
        title: Optional[str] = None
        description: Optional[str] = None
        thumbnail: Optional[str] = None

        # ── Try JSON-LD ──────────────────────────────────────────
        ld_blocks = re.findall(
            r'<script\s+type="application/ld\+json"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        for block in ld_blocks:
            try:
                data = json.loads(block)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    img = item.get("image")
                    if isinstance(img, dict):
                        img = img.get("contentUrl") or img.get("url")
                    if isinstance(img, list):
                        img = img[0] if img else None
                    if img and "pinimg.com" in str(img):
                        original_url = re.sub(r"/\d+x/", "/originals/", str(img))
                        thumbnail = original_url
                        variants.append(
                            ScrapedVariant(
                                label="Original", format="jpg", url=original_url,
                            )
                        )
                    title = title or item.get("name") or item.get("headline")
                    description = description or item.get("description")
                    # Video content
                    video = item.get("video")
                    if isinstance(video, dict):
                        video_url = video.get("contentUrl")
                        if video_url:
                            variants.insert(
                                0,
                                ScrapedVariant(
                                    label="Video",
                                    format="mp4",
                                    url=video_url,
                                    has_video=True,
                                    has_audio=True,
                                ),
                            )
            except (json.JSONDecodeError, TypeError, KeyError):
                continue

        # ── Try __PWS_DATA__ (Pinterest's embedded JSON) ─────────
        if not variants:
            pws_match = re.search(
                r'<script\s+id="__PWS_DATA__"[^>]*>(.*?)</script>',
                html,
                re.DOTALL,
            )
            if pws_match:
                try:
                    pws = json.loads(pws_match.group(1))
                    pin_data = _find_pin_data(pws)
                    if pin_data:
                        images = pin_data.get("images", {})
                        orig = images.get("orig", {})
                        if orig.get("url"):
                            thumbnail = orig["url"]
                            variants.append(
                                ScrapedVariant(
                                    label="Original", format="jpg", url=orig["url"],
                                )
                            )
                        videos = pin_data.get("videos", {})
                        vid_list = videos.get("video_list", {})
                        for key in ("V_HLSV4", "V_720P", "V_480P", "V_EXP7"):
                            v = vid_list.get(key, {})
                            if v.get("url"):
                                variants.insert(
                                    0,
                                    ScrapedVariant(
                                        label=key.replace("V_", ""),
                                        format="mp4",
                                        url=v["url"],
                                        has_video=True,
                                        has_audio=True,
                                    ),
                                )
                                break
                        title = title or pin_data.get("grid_title") or pin_data.get("title")
                        description = description or pin_data.get("description")
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass

        # ── Fallback: regex for pinimg.com originals ─────────────
        if not variants:
            orig_images = re.findall(
                r"(https://i\.pinimg\.com/originals/[^\s\"']+\.(?:jpg|png|gif|webp))",
                html,
            )
            if not orig_images:
                orig_images = re.findall(
                    r"(https://i\.pinimg\.com/[^\s\"']+\.(?:jpg|png|gif|webp))",
                    html,
                )
            seen: set[str] = set()
            for img_url in orig_images:
                if img_url not in seen:
                    seen.add(img_url)
                    if not thumbnail:
                        thumbnail = img_url
                    variants.append(
                        ScrapedVariant(label="Image", format="jpg", url=img_url)
                    )

        if not variants:
            return None

        content_type = "video" if any(v.has_video for v in variants) else "image"
        return ScrapedResult(
            title=title or "Pinterest Pin",
            description=description,
            thumbnail_url=thumbnail,
            content_type=content_type,
            variants=variants,
        )


def _find_pin_data(obj: object, depth: int = 0) -> Optional[dict]:
    """Recursively walk a nested dict looking for a pin data object."""
    if depth > 8:
        return None
    if isinstance(obj, dict):
        if "images" in obj and isinstance(obj["images"], dict):
            return obj
        for v in obj.values():
            found = _find_pin_data(v, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj[:20]:
            found = _find_pin_data(item, depth + 1)
            if found:
                return found
    return None
