"""
Pinterest scraper – extracts pins (images and video pins).

Strategy:
  1. Pinterest Resource API (best source — returns video URLs + originals)
  2. yt-dlp (handles some video pins)
  3. Page HTML parsing (OG tags, JSON-LD, __PWS_DATA__ legacy, regex)
  4. Playwright browser-rendered fetch as last resort
"""

import re
import json
import structlog
from html import unescape
from typing import Optional
from urllib.parse import quote

from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.services.scrapers.helpers import build_ytdlp_variants, parse_og_tags
from app.utils.ytdlp_helper import extract_with_ytdlp
from app.utils.browser import get_page_content
from app.utils.http_client import get_http_client

logger = structlog.get_logger()

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _upgrade_pinimg_url(url: str) -> str:
    """Upgrade a pinimg.com thumbnail URL to the original quality.

    Pinterest CDN URLs look like:
      https://i.pinimg.com/736x/1d/e6/8d/...jpg  (736px wide)
      https://i.pinimg.com/236x/...jpg             (236px wide)
      https://i.pinimg.com/originals/...jpg         (full size)

    We replace the size prefix with 'originals' for full resolution.
    """
    if "pinimg.com" not in url:
        return url
    return re.sub(r"pinimg\.com/\d+x/", "pinimg.com/originals/", url)


class PinterestScraper(BaseScraper):
    platform = "pinterest"

    _DOMAIN_RE = re.compile(r"(pinterest\.com|pin\.it)")

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        # Resolve short URLs  (pin.it → pinterest.com)
        resolved_url = await self._resolve_url(url)
        pin_id = self._extract_pin_id(resolved_url)

        # ── Strategy 1: Pinterest Resource API ───────────────────
        if pin_id:
            try:
                result = await self._try_resource_api(pin_id)
                if result and result.variants:
                    return result
            except Exception as exc:
                logger.debug("pinterest_api_error", error=str(exc)[:80])

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

        # ── Strategy 3: Page HTML parsing ────────────────────────
        html = await get_page_content(resolved_url)
        if html:
            result = self._parse_pin_page(html)
            if result and result.variants:
                return result

        # ── Strategy 4: Playwright browser-rendered fetch ────────
        try:
            browser_html = await get_page_content(
                resolved_url, use_browser=True, timeout_ms=15_000,
            )
            if browser_html:
                result = self._parse_pin_page(browser_html)
                if result and result.variants:
                    return result
        except Exception:
            pass

        # ── Strategy 5: OG-tag fallback ──────────────────────────
        if html:
            result = parse_og_tags(html, "Pinterest Pin", "image")
            if result.variants:
                # Upgrade image quality
                for v in result.variants:
                    v.url = _upgrade_pinimg_url(v.url)
                if result.thumbnail_url:
                    result.thumbnail_url = _upgrade_pinimg_url(result.thumbnail_url)
                return result

        raise ValueError("Could not extract this Pinterest pin.")

    # ── Pinterest Resource API ───────────────────────────────────

    async def _try_resource_api(self, pin_id: str) -> Optional[ScrapedResult]:
        """Fetch pin data from Pinterest's internal Resource API.

        This is the same API Pinterest's frontend uses. It returns
        full-resolution images and video URLs with all formats.
        """
        client = get_http_client()

        # First, get a CSRF token by visiting the pin page
        try:
            page_resp = await client.get(
                f"https://www.pinterest.com/pin/{pin_id}/",
                headers={"User-Agent": _UA},
            )
            csrf_token = ""
            for cookie_name in ("csrftoken", "csrf_token"):
                csrf_token = page_resp.cookies.get(cookie_name, "")
                if csrf_token:
                    break
            cookies = dict(page_resp.cookies)
        except Exception:
            csrf_token = ""
            cookies = {}

        # Build the Resource API request
        options = json.dumps({
            "options": {
                "id": pin_id,
                "field_set_key": "detailed",
            },
        })
        api_url = (
            f"https://www.pinterest.com/resource/PinResource/get/"
            f"?source_url=/pin/{pin_id}/"
            f"&data={quote(options)}"
        )

        headers = {
            "User-Agent": _UA,
            "Accept": "application/json, text/javascript, */*",
            "X-Requested-With": "XMLHttpRequest",
            "X-APP-VERSION": "0",
            "Referer": f"https://www.pinterest.com/pin/{pin_id}/",
            "Origin": "https://www.pinterest.com",
        }
        if csrf_token:
            headers["X-CSRFToken"] = csrf_token

        resp = await client.get(api_url, headers=headers, cookies=cookies)
        if resp.status_code != 200:
            logger.debug("pinterest_api_status", status=resp.status_code)
            return None

        data = resp.json()
        pin_data = data.get("resource_response", {}).get("data", {})
        if not pin_data:
            return None

        return self._build_result_from_api(pin_data)

    @staticmethod
    def _build_result_from_api(pin_data: dict) -> Optional[ScrapedResult]:
        """Build ScrapedResult from Pinterest Resource API pin data."""
        variants: list[ScrapedVariant] = []
        thumbnail: Optional[str] = None

        # ── Extract videos ───────────────────────────────────────
        videos = pin_data.get("videos", {})
        vid_list = videos.get("video_list", {})
        for key in ("V_720P", "V_480P", "V_EXP7", "V_HLSV4", "V_HLSV3_MOBILE"):
            v = vid_list.get(key, {})
            v_url = v.get("url", "")
            if v_url:
                is_hls = ".m3u8" in v_url or "HLS" in key
                fmt = "m3u8" if is_hls else "mp4"
                h = v.get("height", 0)
                label = f"{h}p" if h else key.replace("V_", "")
                variants.append(
                    ScrapedVariant(
                        label=label, format=fmt, url=v_url,
                        has_video=True, has_audio=True,
                    )
                )

        # ── Extract images ───────────────────────────────────────
        images = pin_data.get("images", {})
        orig = images.get("orig", {})
        if orig.get("url"):
            thumbnail = orig["url"]
            # Always add the original image as a variant
            variants.append(
                ScrapedVariant(label="Original Image", format="jpg", url=orig["url"])
            )
        elif images:
            # Try getting the largest available image
            for key in ("1200x", "736x", "474x", "236x"):
                img = images.get(key, {})
                if img.get("url"):
                    upgraded = _upgrade_pinimg_url(img["url"])
                    thumbnail = upgraded
                    variants.append(
                        ScrapedVariant(label="Image", format="jpg", url=upgraded)
                    )
                    break

        if not variants:
            return None

        title = pin_data.get("grid_title") or pin_data.get("title") or ""
        description = pin_data.get("description")
        author = pin_data.get("pinner", {}).get("username")
        content_type = "video" if any(v.has_video for v in variants) else "image"

        logger.info("pinterest_api_success",
                     content_type=content_type, variants=len(variants))
        return ScrapedResult(
            title=title or "Pinterest Pin",
            description=description,
            author=author,
            thumbnail_url=thumbnail,
            content_type=content_type,
            variants=variants,
        )

    # ── URL helpers ──────────────────────────────────────────────

    async def _resolve_url(self, url: str) -> str:
        """Resolve pin.it short URLs to full pinterest.com URLs."""
        if "pin.it" not in url:
            return url
        try:
            client = get_http_client()
            resp = await client.head(url)
            return str(resp.url)
        except Exception:
            return url

    @staticmethod
    def _extract_pin_id(url: str) -> Optional[str]:
        """Extract the numeric pin ID from a Pinterest URL."""
        # Standard: /pin/633387443245752/
        m = re.search(r"/pin/(?:[^/]*--)?(\d+)", url)
        if m:
            return m.group(1)
        # Fallback: last numeric segment
        m = re.search(r"/(\d{10,})", url)
        return m.group(1) if m else None

    # ── Page HTML parsing (fallback) ─────────────────────────────

    @staticmethod
    def _parse_pin_page(html: str) -> Optional[ScrapedResult]:
        """Extract pin media from page HTML (JSON-LD, __PWS_DATA__, regex)."""
        variants: list[ScrapedVariant] = []
        title: Optional[str] = None
        description: Optional[str] = None
        thumbnail: Optional[str] = None

        # ── Try __PWS_DATA__ ─────────────────────────────────────
        pws_match = re.search(
            r'<script\s+id="__PWS_DATA__"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        if pws_match:
            try:
                pws = json.loads(pws_match.group(1))
                pin_data = _find_pin_data(pws)
                if pin_data:
                    # Extract videos
                    videos = pin_data.get("videos", {})
                    vid_list = videos.get("video_list", {})
                    added_video = False
                    for key in ("V_720P", "V_480P", "V_EXP7", "V_HLSV4"):
                        v = vid_list.get(key, {})
                        if v.get("url"):
                            h = v.get("height", 0)
                            is_hls = ".m3u8" in v["url"] or "HLS" in key
                            variants.append(ScrapedVariant(
                                label=f"{h}p" if h else key.replace("V_", ""),
                                format="m3u8" if is_hls else "mp4",
                                url=v["url"], has_video=True, has_audio=True,
                            ))
                            added_video = True

                    # Extract images
                    images = pin_data.get("images", {})
                    orig = images.get("orig", {})
                    if orig.get("url"):
                        thumbnail = orig["url"]
                        if not added_video:
                            variants.append(ScrapedVariant(
                                label="Original", format="jpg", url=orig["url"],
                            ))

                    title = pin_data.get("grid_title") or pin_data.get("title")
                    description = pin_data.get("description")
            except (json.JSONDecodeError, TypeError, KeyError):
                pass

        # ── Try JSON-LD ──────────────────────────────────────────
        if not variants:
            ld_blocks = re.findall(
                r'<script\s+type="application/ld\+json"[^>]*>(.*?)</script>',
                html, re.DOTALL,
            )
            for block in ld_blocks:
                try:
                    data = json.loads(block)
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        video = item.get("video")
                        if isinstance(video, dict):
                            video_url = video.get("contentUrl")
                            if video_url:
                                variants.insert(0, ScrapedVariant(
                                    label="Video", format="mp4", url=video_url,
                                    has_video=True, has_audio=True,
                                ))
                        img = item.get("image")
                        if isinstance(img, dict):
                            img = img.get("contentUrl") or img.get("url")
                        if isinstance(img, list):
                            img = img[0] if img else None
                        if img and "pinimg.com" in str(img):
                            original_url = _upgrade_pinimg_url(str(img))
                            thumbnail = original_url
                            if not any(v.has_video for v in variants):
                                variants.append(ScrapedVariant(
                                    label="Original", format="jpg", url=original_url,
                                ))
                        title = title or item.get("name") or item.get("headline")
                        description = description or item.get("description")
                except (json.JSONDecodeError, TypeError, KeyError):
                    continue

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
        if ("images" in obj and isinstance(obj["images"], dict)) or \
           ("videos" in obj and isinstance(obj["videos"], dict)):
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
