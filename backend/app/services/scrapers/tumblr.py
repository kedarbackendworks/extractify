"""
Tumblr scraper – extracts GIFs, videos, photos, reblogs, and text posts.

Strategies (in priority order):
  1. Tumblr embed page  (embed.tumblr.com – lightweight, no SPA)
  2. Tumblr API v2      (public, no auth needed for published posts)
  3. yt-dlp             (video posts)
  4. Playwright browser  (full SPA render, last resort)
"""

import json
import re
from html import unescape
from typing import Optional
from urllib.parse import urlparse

import httpx
import structlog

from app.core.config import settings
from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.services.scrapers.helpers import build_ytdlp_variants, parse_og_tags, find_og_tag
from app.utils.ytdlp_helper import extract_with_ytdlp
from app.utils.browser import get_page_content

logger = structlog.get_logger()

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.tumblr.com/",
}

# Override via TUMBLR_API_KEYS env var (comma-separated).
_DEFAULT_API_KEYS: list[str] = []


def _get_tumblr_api_keys() -> list[str]:
    """Return Tumblr API keys from env, falling back to hardcoded defaults."""
    raw = settings.TUMBLR_API_KEYS
    if raw:
        return [k.strip() for k in raw.split(",") if k.strip()]
    return _DEFAULT_API_KEYS


class TumblrScraper(BaseScraper):
    platform = "tumblr"

    _DOMAIN_RE = re.compile(r"(tumblr\.com|[a-z0-9-]+\.tumblr\.com)")

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        blog_name, post_id = self._parse_url(url)

        # ── Strategy 1: Tumblr embed page (fast, lightweight) ────
        if blog_name and post_id:
            try:
                result = await self._scrape_embed(blog_name, post_id, content_tab)
                if result and result.variants:
                    return result
            except Exception as exc:
                logger.debug("tumblr_embed_failed", error=str(exc))

        # ── Strategy 2: Tumblr API v2 ────────────────────────────
        if blog_name and post_id:
            try:
                result = await self._scrape_api(blog_name, post_id, content_tab)
                if result and result.variants:
                    return result
            except Exception as exc:
                logger.debug("tumblr_api_failed", error=str(exc))

        # ── Strategy 3: yt-dlp (video posts) ─────────────────────
        try:
            info = await extract_with_ytdlp(url)
            variants = build_ytdlp_variants(info)
            if variants:
                return ScrapedResult(
                    title=info.get("title", "Tumblr Video"),
                    description=info.get("description"),
                    author=info.get("uploader") or blog_name,
                    thumbnail_url=info.get("thumbnail"),
                    duration_seconds=info.get("duration"),
                    content_type="video",
                    variants=variants,
                )
        except Exception as exc:
            logger.debug("tumblr_ytdlp_failed", error=str(exc))

        # ── Strategy 4: Playwright full-browser render ───────────
        try:
            html = await get_page_content(
                url, use_browser=True, timeout_ms=25_000,
            )
            if html:
                result = self._parse_html_for_media(html, blog_name, content_tab)
                if result and result.variants:
                    return result
                # OG-tag fallback
                result = parse_og_tags(html, "Tumblr Post", "other")
                if result.variants:
                    result.author = result.author or blog_name
                    return result
        except Exception as exc:
            logger.debug("tumblr_playwright_failed", error=str(exc))

        raise ValueError("Could not extract content from this Tumblr post.")

    # ─────────────────────────────────────────────────────────────
    #  URL parsing
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_url(url: str) -> tuple[Optional[str], Optional[str]]:
        """
        Extract (blog_name, post_id) from a Tumblr URL.

        Supported formats:
          - https://blogname.tumblr.com/post/123456/slug
          - https://www.tumblr.com/blogname/123456/slug
          - https://www.tumblr.com/blog/blogname/123456
        """
        parsed = urlparse(url)
        host = parsed.hostname or ""
        path = parsed.path.strip("/")
        parts = path.split("/")

        # Subdomain blog: blogname.tumblr.com/post/12345
        if host.endswith(".tumblr.com") and host != "www.tumblr.com":
            blog_name = host.replace(".tumblr.com", "")
            post_id = None
            if len(parts) >= 2 and parts[0] == "post":
                post_id = parts[1]
            return blog_name, post_id

        # www.tumblr.com/blogname/12345  or  www.tumblr.com/blog/blogname/12345
        if host in ("www.tumblr.com", "tumblr.com"):
            if len(parts) >= 3 and parts[0] == "blog":
                # /blog/blogname/12345
                return parts[1], parts[2] if parts[2].isdigit() else None
            if len(parts) >= 2 and parts[0] not in ("post", "blog", "dashboard"):
                # /blogname/12345
                return parts[0], parts[1] if parts[1].isdigit() else None
            if len(parts) >= 1 and parts[0] not in ("post", "blog", "dashboard"):
                return parts[0], None

        return None, None

    # ─────────────────────────────────────────────────────────────
    #  Strategy 1: Tumblr embed page
    # ─────────────────────────────────────────────────────────────

    async def _scrape_embed(
        self, blog_name: str, post_id: str, content_tab: Optional[str] = None
    ) -> Optional[ScrapedResult]:
        """
        Fetch the lightweight embed page at embed.tumblr.com.
        This endpoint returns simple HTML (not the full SPA) and
        contains direct media URLs. Works without auth.
        """
        embed_url = f"https://embed.tumblr.com/embed/post/{blog_name}/{post_id}"
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, headers=_HEADERS,
        ) as client:
            resp = await client.get(embed_url)
            resp.raise_for_status()
            html = resp.text

        if len(html) < 200:
            return None

        return self._parse_html_for_media(html, blog_name, content_tab)

    # ─────────────────────────────────────────────────────────────
    #  Strategy 2: Tumblr API v2
    # ─────────────────────────────────────────────────────────────

    async def _scrape_api(
        self, blog_name: str, post_id: str, content_tab: Optional[str] = None
    ) -> Optional[ScrapedResult]:
        last_exc: Optional[Exception] = None
        for api_key in _get_tumblr_api_keys():
            api_url = (
                f"https://api.tumblr.com/v2/blog/{blog_name}.tumblr.com"
                f"/posts?id={post_id}&api_key={api_key}&npf=true"
            )
            try:
                async with httpx.AsyncClient(
                    timeout=15, headers={"User-Agent": _UA},
                ) as client:
                    resp = await client.get(api_url)
                    resp.raise_for_status()

                data = resp.json()
                posts = data.get("response", {}).get("posts", [])
                if not posts:
                    continue

                post = posts[0]
                return self._parse_api_post(post, content_tab)
            except Exception as exc:
                last_exc = exc
                continue

        if last_exc:
            raise last_exc
        return None

    def _parse_api_post(
        self, post: dict, content_tab: Optional[str] = None
    ) -> Optional[ScrapedResult]:
        """Parse a single post from the v2 API (NPF format)."""
        variants: list[ScrapedVariant] = []
        title: Optional[str] = None
        description_parts: list[str] = []
        thumbnail: Optional[str] = None
        blog_name = post.get("blog_name") or post.get("blog", {}).get("name")
        post_type = post.get("type", "text")
        is_reblog = bool(post.get("reblogged_from_name"))
        duration: Optional[float] = None

        # NPF content blocks
        content_blocks = post.get("content", [])
        trail = post.get("trail", [])

        for block in content_blocks:
            block_type = block.get("type")

            if block_type == "text":
                text = block.get("text", "")
                if text:
                    description_parts.append(text)

            elif block_type == "image":
                media_list = block.get("media", [])
                if media_list:
                    # Pick the highest-resolution image
                    best = max(media_list, key=lambda m: m.get("width", 0))
                    img_url = best.get("url", "")
                    if img_url:
                        is_gif = best.get("type") == "image/gif" or img_url.endswith(".gif")
                        if not thumbnail:
                            thumbnail = img_url
                        variants.append(
                            ScrapedVariant(
                                label="GIF" if is_gif else "Photo",
                                format="gif" if is_gif else _ext_from_url(img_url),
                                url=img_url,
                            )
                        )

            elif block_type == "video":
                video_url = block.get("url")
                media = block.get("media", {})
                if not video_url and media:
                    video_url = media.get("url")
                poster = block.get("poster", [])
                if poster:
                    best_poster = max(poster, key=lambda p: p.get("width", 0))
                    thumbnail = thumbnail or best_poster.get("url")
                duration = block.get("duration") or media.get("duration")
                if video_url:
                    variants.append(
                        ScrapedVariant(
                            label="Video",
                            format=_ext_from_url(video_url),
                            url=video_url,
                            has_video=True,
                            has_audio=True,
                        )
                    )

            elif block_type == "audio":
                audio_url = block.get("url")
                media = block.get("media", {})
                if not audio_url and media:
                    audio_url = media.get("url")
                if audio_url:
                    variants.append(
                        ScrapedVariant(
                            label="Audio",
                            format=_ext_from_url(audio_url),
                            url=audio_url,
                            has_video=False,
                            has_audio=True,
                        )
                    )

        # Reblog trail may contain additional media
        for entry in trail:
            for block in entry.get("content", []):
                block_type = block.get("type")
                if block_type == "image":
                    media_list = block.get("media", [])
                    if media_list:
                        best = max(media_list, key=lambda m: m.get("width", 0))
                        img_url = best.get("url", "")
                        if img_url and not any(v.url == img_url for v in variants):
                            is_gif = best.get("type") == "image/gif" or img_url.endswith(".gif")
                            variants.append(
                                ScrapedVariant(
                                    label=f"Reblog {'GIF' if is_gif else 'Photo'}",
                                    format="gif" if is_gif else _ext_from_url(img_url),
                                    url=img_url,
                                )
                            )
                elif block_type == "video":
                    video_url = block.get("url") or (block.get("media") or {}).get("url")
                    if video_url and not any(v.url == video_url for v in variants):
                        variants.append(
                            ScrapedVariant(
                                label="Reblog Video",
                                format=_ext_from_url(video_url),
                                url=video_url,
                                has_video=True,
                                has_audio=True,
                            )
                        )

        # Determine content type
        if content_tab == "Text Posts" or (not variants and description_parts):
            content_type = "text"
        elif content_tab == "Reblogs" or is_reblog:
            content_type = "reblog"
        elif any(v.has_video for v in variants):
            content_type = "video"
        elif any(v.format == "gif" for v in variants):
            content_type = "gif"
        elif variants:
            content_type = "image"
        else:
            content_type = "text"

        # Build title from summary or first text block
        summary = post.get("summary", "")
        title = summary if summary else (description_parts[0][:80] if description_parts else None)

        # For text posts with no media, create a text-content variant
        if not variants and description_parts:
            full_text = "\n\n".join(description_parts)
            # No downloadable media, but we surface the text
            variants.append(
                ScrapedVariant(
                    label="Text Post",
                    format="txt",
                    url=post.get("post_url", ""),
                )
            )

        if not variants:
            return None

        return ScrapedResult(
            title=title or "Tumblr Post",
            description="\n\n".join(description_parts) if description_parts else None,
            author=blog_name,
            thumbnail_url=thumbnail,
            duration_seconds=duration,
            content_type=content_type,
            variants=variants,
        )

    # ─────────────────────────────────────────────────────────────
    #  Shared HTML media extractor
    # ─────────────────────────────────────────────────────────────

    def _parse_html_for_media(
        self, html: str, blog_name: Optional[str] = None,
        content_tab: Optional[str] = None,
    ) -> Optional[ScrapedResult]:
        """Extract media from any Tumblr HTML (embed page or full page)."""
        variants: list[ScrapedVariant] = []
        title: Optional[str] = None
        description: Optional[str] = None
        thumbnail: Optional[str] = None

        # ── Try ___INITIAL_STATE___ JSON (full page) ─────────────
        state_match = re.search(
            r'window\[\'___INITIAL_STATE___\'\]\s*=\s*(\{.*?\});?\s*</script>',
            html,
            re.DOTALL,
        )
        if state_match:
            try:
                state = json.loads(state_match.group(1))
                post_data = self._dig_post_from_state(state)
                if post_data:
                    result = self._parse_api_post(post_data, content_tab)
                    if result and result.variants:
                        return result
            except (json.JSONDecodeError, TypeError):
                pass

        # ── Regex extraction of media URLs ───────────────────────
        # GIFs  (64.media.tumblr.com, media.tumblr.com patterns)
        gif_urls = re.findall(
            r'(https?://[0-9a-z]+\.media\.tumblr\.com/[^\s"\'<>]+\.gif(?:\?[^\s"\'<>]*)?)',
            html,
        )
        for gif_url in _dedupe(gif_urls):
            clean = unescape(gif_url).split("?")[0]
            variants.append(
                ScrapedVariant(label="GIF", format="gif", url=clean)
            )
            if not thumbnail:
                thumbnail = clean

        # Videos (va.media.tumblr.com, ve.media.tumblr.com, vtt…)
        video_urls = re.findall(
            r'(https?://(?:va|ve|vtt|v)[a-z0-9]*\.media\.tumblr\.com/[^\s"\'<>]+\.mp4(?:\?[^\s"\'<>]*)?)',
            html,
        )
        # Also catch video src in <source> and data-src attributes
        video_urls += re.findall(
            r'(?:src|data-src)=["\']?(https?://[^\s"\'<>]+\.tumblr\.com/[^\s"\'<>]+\.mp4[^\s"\'<>]*)',
            html,
        )
        for vid_url in _dedupe(video_urls):
            clean = unescape(vid_url).split("?")[0]
            if not any(v.url == clean for v in variants):
                variants.append(
                    ScrapedVariant(
                        label="Video", format="mp4", url=clean,
                        has_video=True, has_audio=True,
                    )
                )

        # Photos (high-res jpg/png/webp)
        photo_urls = re.findall(
            r'(https?://[0-9a-z]+\.media\.tumblr\.com/[^\s"\'<>]+\.(?:jpg|jpeg|png|webp)(?:\?[^\s"\'<>]*)?)',
            html,
        )
        for clean in _clean_and_dedupe_photos(photo_urls):
            if not any(v.url == clean for v in variants):
                variants.append(
                    ScrapedVariant(
                        label="Photo", format=_ext_from_url(clean), url=clean,
                    )
                )
                if not thumbnail:
                    thumbnail = clean

        # OG tags for metadata
        og_title = find_og_tag(html, "og:title")
        og_desc = find_og_tag(html, "og:description")
        if og_title and og_title.lower() not in ("tumblr", ""):
            title = unescape(og_title)
        if og_desc:
            description = unescape(og_desc)

        # Extract blog name from embed HTML if not provided
        if not blog_name:
            m = re.search(r'"name"\s*:\s*"([^"]+)"', html)
            if m:
                blog_name = m.group(1)

        if not variants:
            return None

        content_type = "video" if any(v.has_video for v in variants) else (
            "gif" if any(v.format == "gif" for v in variants) else "image"
        )

        # Build a meaningful title
        if not title and blog_name:
            type_label = content_type.capitalize() if content_type != "image" else "Photo"
            title = f"{blog_name} – {type_label} Post"

        return ScrapedResult(
            title=title or "Tumblr Post",
            description=description,
            author=blog_name,
            thumbnail_url=thumbnail,
            content_type=content_type,
            variants=variants,
        )

    @staticmethod
    def _dig_post_from_state(state: dict) -> Optional[dict]:
        """Dive into ___INITIAL_STATE___ to find the first post object."""
        try:
            queries = state.get("queries", {}).get("queries", [])
            for q in queries:
                qstate = q.get("state", {})
                data = qstate.get("data", {})
                timeline = data.get("timeline", data)
                elements = timeline.get("elements", [])
                for el in elements:
                    if el.get("objectType") == "post" or el.get("content"):
                        return el
                if data.get("content") or data.get("type"):
                    return data
        except (AttributeError, TypeError):
            pass
        return None


# ─────────────────────────────────────────────────────────────────
#  Module-level helpers
# ─────────────────────────────────────────────────────────────────


def _ext_from_url(url: str) -> str:
    """Guess file extension from URL path."""
    path = urlparse(url).path
    if "." in path:
        ext = path.rsplit(".", 1)[-1].lower()
        if ext in ("jpg", "jpeg", "png", "gif", "webp", "mp4", "webm", "mp3", "m4a"):
            return ext
    return "mp4"


def _clean_media_url(url: str) -> str:
    """Unescape HTML entities and strip query params."""
    return unescape(url).split("?")[0]


def _clean_and_dedupe_photos(raw_urls: list[str]) -> list[str]:
    """
    Tumblr serves the same image at many sizes (s64x64, s250x250, s2048x3072…).
    Group by the unique hash prefix and keep only the highest-res URL per image.
    """
    best: dict[str, tuple[int, str]] = {}  # hash_prefix -> (width, url)
    for raw in raw_urls:
        url = unescape(raw).split("?")[0]
        # Extract the unique part: everything up to /s<W>x<H>
        m = re.match(
            r'(https?://[0-9a-z]+\.media\.tumblr\.com/[^/]+/[^/]+)/s(\d+)x(\d+)',
            url,
        )
        if m:
            prefix = m.group(1)
            width = int(m.group(2))
            if prefix not in best or width > best[prefix][0]:
                best[prefix] = (width, url)
        else:
            # Non-standard URL – keep as is
            best[url] = (0, url)

    return [url for _, url in best.values()]


def _dedupe(urls: list[str]) -> list[str]:
    """De-duplicate a list while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out
