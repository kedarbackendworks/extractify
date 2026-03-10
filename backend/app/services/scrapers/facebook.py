"""
Facebook scraper – authenticated extraction for Videos, Reels, Stories,
Photos, and Live content.

Strategies:
  Videos / Reels / Live → yt-dlp (cookies) → Playwright (cookies)
  Stories               → Playwright (full cookies) + GraphQL interception
  Photos                → Playwright (cookies) → high-res CDN extraction

NOTE: yt-dlp does NOT support Facebook ``/stories/`` URLs.  Its Facebook
extractor only matches ``/watch/``, ``/videos/``, ``/reel/``, ``story.php``,
etc.  Story extraction relies entirely on headless Playwright with a full
cookie jar and network-level interception of Facebook's Relay/GraphQL
responses that carry ``playable_url`` and image ``uri`` values.
"""

import asyncio
import os
import re
import tempfile
import traceback
import structlog
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from typing import Optional

from app.core.config import settings
from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.services.scrapers.helpers import build_ytdlp_variants, parse_og_tags
from app.utils.ytdlp_helper import extract_with_ytdlp
from app.utils.browser import get_page_content

logger = structlog.get_logger()

_story_thread_pool = ThreadPoolExecutor(max_workers=2)


# ─────────────────────────────────────────────────────────────────
#  Session cookie helpers
# ─────────────────────────────────────────────────────────────────

def _has_fb_session() -> bool:
    """Check if Facebook session credentials are configured."""
    cookie_file = _get_fb_cookies_file()
    return bool(
        (settings.FACEBOOK_C_USER and settings.FACEBOOK_XS)
        or cookie_file
    )


def _get_fb_cookies() -> dict[str, str]:
    """Build a cookie dict from the Facebook session settings."""
    cookies: dict[str, str] = {}
    if settings.FACEBOOK_C_USER:
        cookies["c_user"] = settings.FACEBOOK_C_USER
    if settings.FACEBOOK_XS:
        cookies["xs"] = settings.FACEBOOK_XS
    return cookies


def _parse_netscape_cookies(filepath: str) -> list[dict]:
    """Parse a Netscape-format cookies.txt into a Playwright-compatible list.

    Each non-comment, non-blank line has 7 tab-separated fields:
      domain  flag  path  secure  expiry  name  value
    """
    cookies: list[dict] = []
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("//"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                domain, _flag, path, secure, _expiry, name, value = parts[:7]
                cookies.append({
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": path or "/",
                    "secure": secure.upper() == "TRUE",
                })
    except Exception as exc:
        logger.warning("fb_parse_cookie_file_err", error=repr(exc)[:120])
    return cookies


def _get_full_playwright_cookies() -> list[dict]:
    """Build the richest possible Playwright cookie list.

    Priority 1: Parse ALL cookies from the Netscape cookie file
    Priority 2: Fall back to c_user + xs from .env (minimal, often insufficient)
    """
    cookie_file = _get_fb_cookies_file()
    if cookie_file:
        parsed = _parse_netscape_cookies(cookie_file)
        if parsed:
            logger.debug("fb_pw_cookies_from_file", count=len(parsed))
            return parsed

    # Minimal fallback – only c_user and xs
    basic = _get_fb_cookies()
    if basic:
        return [
            {"name": n, "value": v, "domain": ".facebook.com", "path": "/"}
            for n, v in basic.items()
        ]
    return []


def _get_playwright_cookies() -> list[dict]:
    """Build Playwright-compatible cookie list for Facebook.

    Delegates to _get_full_playwright_cookies for the richest set.
    """
    return _get_full_playwright_cookies()


def _get_fb_cookies_file() -> Optional[str]:
    """Resolve or auto-generate a Netscape cookies file for yt-dlp."""
    # Priority 1: Explicit Facebook cookies file
    if settings.FACEBOOK_COOKIES_FILE:
        if os.path.isfile(settings.FACEBOOK_COOKIES_FILE):
            return settings.FACEBOOK_COOKIES_FILE
        abs_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            settings.FACEBOOK_COOKIES_FILE,
        )
        if os.path.isfile(abs_path):
            return abs_path

    # Priority 2: General yt-dlp cookie file
    if settings.YTDLP_COOKIES_FILE and os.path.isfile(settings.YTDLP_COOKIES_FILE):
        return settings.YTDLP_COOKIES_FILE

    # Priority 3: Auto-generate from session cookies
    if settings.FACEBOOK_C_USER and settings.FACEBOOK_XS:
        try:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix="_fb_cookies.txt",
                delete=False, prefix="extractify_",
            )
            tmp.write("# Netscape HTTP Cookie File\n")
            for name, value in _get_fb_cookies().items():
                tmp.write(f".facebook.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n")
            tmp.close()
            return tmp.name
        except Exception as exc:
            logger.debug("fb_temp_cookie_file_error", error=str(exc))
    return None


class FacebookScraper(BaseScraper):
    platform = "facebook"
    _DOMAIN_RE = re.compile(r"(facebook\.com|fb\.com|fb\.watch)")

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        # URL-based routing takes priority over content_tab to avoid
        # mis-routing (e.g. a /stories/ URL sent with tab="Videos").
        if "/stories/" in url:
            return await self._scrape_story(url)

        if "/reel/" in url or "/watch/" in url or "/videos/" in url or "fb.watch" in url:
            return await self._scrape_video(url)

        if "/photo" in url:
            return await self._scrape_photo(url)

        # Content tab hint (when URL alone is ambiguous)
        if content_tab in ("Videos", "Reels", "Live"):
            return await self._scrape_video(url)
        if content_tab == "Photos":
            return await self._scrape_photo(url)
        if content_tab == "Stories":
            return await self._scrape_story(url)

        # Fallback: try video, then photo
        try:
            return await self._scrape_video(url)
        except Exception:
            return await self._scrape_photo(url)

    # ─────────────────────────────────────────────────────────────
    #  Core extraction methods
    # ─────────────────────────────────────────────────────────────

    async def _scrape_video(self, url: str) -> ScrapedResult:
        """Extract video using yt-dlp with cookies, fallback to Playwright."""
        cookie_file = _get_fb_cookies_file()
        has_session = _has_fb_session()

        # Strategy 1: yt-dlp with cookies
        if cookie_file:
            try:
                info = await extract_with_ytdlp(url, extra_opts={"cookiefile": cookie_file})
                variants = build_ytdlp_variants(info)
                if variants:
                    return ScrapedResult(
                        title=info.get("title"),
                        description=info.get("description"),
                        author=info.get("uploader"),
                        thumbnail_url=info.get("thumbnail"),
                        duration_seconds=info.get("duration"),
                        content_type="reel" if "/reel/" in url else "video",
                        variants=variants,
                    )
            except Exception as exc:
                logger.debug("fb_ytdlp_cookies_error", error=str(exc)[:80])

        # Strategy 2: yt-dlp plain (public videos)
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
                    content_type="reel" if "/reel/" in url else "video",
                    variants=variants,
                )
        except Exception:
            pass

        # Strategy 3: Playwright with cookies
        pw_cookies = _get_playwright_cookies() if has_session else None
        html = await get_page_content(url, use_browser=True, cookies=pw_cookies)
        if html:
            result = parse_og_tags(html, "Facebook Video", "video")
            if result.variants:
                return result

            # Try extracting video CDN URLs from rendered page
            result = self._extract_cdn_media(html, "video")
            if result and result.variants:
                return result

        error_msg = "Could not extract this Facebook video. It may be private or require authentication."
        if not has_session:
            error_msg += " TIP: Configure FACEBOOK_C_USER and FACEBOOK_XS in .env."
        raise ValueError(error_msg)

    async def _scrape_photo(self, url: str) -> ScrapedResult:
        """Extract photo via Playwright with cookies + high-res image parsing."""
        has_session = _has_fb_session()
        pw_cookies = _get_playwright_cookies() if has_session else None

        html = await get_page_content(url, use_browser=True, cookies=pw_cookies)
        if html:
            # Try OG tags first
            result = parse_og_tags(html, "Facebook Photo", "image")
            if result.variants:
                return result

            # Extract high-res images from rendered page
            variants: list[ScrapedVariant] = []
            seen: set[str] = set()
            for raw in re.findall(
                r"(https://(?:scontent|external)[^\s\"']+\.(?:jpg|png|webp)[^\s\"']*)",
                html,
            ):
                clean = unescape(raw)
                if clean not in seen and "emoji" not in clean:
                    seen.add(clean)
                    variants.append(ScrapedVariant(
                        label=f"Image {len(variants) + 1}",
                        format="jpg", url=clean,
                    ))

            if variants:
                return ScrapedResult(
                    title="Facebook Photo",
                    thumbnail_url=variants[0].url,
                    content_type="image", variants=variants,
                )

        error_msg = "Could not extract this Facebook photo. It may be private or require authentication."
        if not has_session:
            error_msg += " TIP: Configure FACEBOOK_C_USER and FACEBOOK_XS in .env."
        raise ValueError(error_msg)

    async def _scrape_story(self, url: str) -> ScrapedResult:
        """
        Stories extraction via Playwright + GraphQL response interception.

        yt-dlp does NOT support Facebook /stories/ URLs (its extractor regex
        only matches /watch/, /videos/, /reel/, story.php, etc.).  We rely
        entirely on headless Playwright with full cookie injection and
        network-level interception of Relay/GraphQL responses which carry
        ``playable_url`` (video) and image ``uri`` values.
        """
        has_session = _has_fb_session()

        if not has_session:
            raise ValueError(
                "Facebook stories require authentication. "
                "Place a facebook_cookies.txt (Netscape format) in the backend "
                "directory, or set FACEBOOK_C_USER + FACEBOOK_XS in .env."
            )

        pw_cookies = _get_full_playwright_cookies()
        logger.info("fb_story_start", url=url[:120], pw_cookies=len(pw_cookies))

        # ── Strategy 1: Playwright + GraphQL interception ────────
        try:
            media = await self._extract_story_media_pw(url, pw_cookies)
            if media:
                return self._build_story_result(media)
        except Exception as exc:
            logger.warning(
                "fb_story_pw_err", error=repr(exc)[:200],
                tb="".join(traceback.format_tb(exc.__traceback__)[-3:]),
            )

        # ── Strategy 2: Playwright basic HTML scraping (fallback) ─
        try:
            html = await get_page_content(url, use_browser=True, cookies=pw_cookies)
            if html:
                if "/login" in html[:5000].lower():
                    raise ValueError("Session cookies expired – Facebook redirected to login.")

                result = self._extract_cdn_media(html, "story")
                if result and result.variants:
                    return result
        except ValueError:
            raise
        except Exception as exc:
            logger.debug("fb_story_html_err", error=repr(exc)[:120])

        raise ValueError(
            "No story content found. Possible reasons:\n"
            "• The story has expired (Facebook stories last 24 hours).\n"
            "• The user has no active stories right now.\n"
            "• Session cookies have expired – re-export facebook_cookies.txt."
        )

    # ─────────────────────────────────────────────────────────────
    #  Playwright-based story media extraction
    # ─────────────────────────────────────────────────────────────

    async def _extract_story_media_pw(
        self, url: str, pw_cookies: list[dict],
    ) -> list[tuple[str, str]]:
        """Run Playwright in a thread-pool, intercept GraphQL responses.

        Returns a list of (type, url) tuples where type is "video" or "image".
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _story_thread_pool,
            self._sync_extract_story_media,
            url,
            pw_cookies,
        )

    @staticmethod
    def _sync_extract_story_media(
        url: str, pw_cookies: list[dict],
    ) -> list[tuple[str, str]]:
        """Synchronous Playwright story extraction (runs in thread).

        Opens the story URL with full cookies, waits for the page to
        hydrate, then extracts media from the embedded React/Relay JSON:

        **Videos** – Facebook embeds ``progressive_urls`` arrays in the
        page's hydration JSON.  Each array corresponds to one story video
        and contains SD (360p) and HD (720p) progressive-download URLs.
        These are **complete, directly downloadable MP4 files** with auth
        tokens baked into the query string (no cookies needed to fetch).

        **Photos** – Photo-only stories embed ``"image":{"uri":"…"}``
        objects.  We pick the highest-resolution variant and skip video
        thumbnails / profile pictures.

        The previous network-interception approach captured CMAF/DASH
        *segment* URLs which returned only the tiny initialisation
        segment (~1 KB) when re-fetched – resulting in corrupt files.
        """
        from playwright.sync_api import sync_playwright
        import sys

        # On Windows, uvicorn sets WindowsSelectorEventLoopPolicy which
        # does NOT support subprocess creation.  Playwright needs the
        # ProactorEventLoop to spawn the browser process.  We restore it
        # for this thread before launching Playwright.
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        media: list[tuple[str, str]] = []   # ("video"|"image", url)
        seen_paths: set[str] = set()

        def _add(kind: str, raw_url: str):
            clean = (
                raw_url
                .replace("\\/", "/")
                .replace("\\u0025", "%")
                .replace("\\u0026", "&")
                .replace("&amp;", "&")
            )
            if len(clean) <= 40:
                return
            path = clean.split("?")[0]
            if path in seen_paths:
                return
            seen_paths.add(path)
            media.append((kind, clean))

        # Patterns for non-story images to skip
        _SKIP_RE = re.compile(
            r"t1\.30497|"            # default FB profile pic
            r"t39\.30808-1|"         # profile photos
            r"t15\.\d+-10|"          # video poster thumbnails
            r"emoji|static|"
            r"hads-ak|"              # ad images
            r"/[sp]\d{2,3}x\d{2,3}[/_]",  # tiny presets
        )

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 720},
            )
            context.add_cookies(pw_cookies)
            page = context.new_page()

            try:
                page.goto(url, wait_until="networkidle", timeout=30_000)
                page.wait_for_timeout(8_000)
            except Exception as exc:
                logger.debug("fb_story_nav_err", error=repr(exc)[:120])

            # Check for login redirect (session expired)
            if "/login" in page.url.lower():
                logger.warning("fb_story_login_redirect")
                browser.close()
                return []

            # ── Extract media from page HTML / JSON ──────────────
            try:
                html = page.content()

                # ── 1. Progressive video URLs (primary) ──────────
                # Each story video has a "progressive_urls" array:
                #   [{"progressive_url":"<url>",…,"metadata":{"quality":"SD"}},
                #    {"progressive_url":"<url>",…,"metadata":{"quality":"HD"}}]
                # We pick HD when available, SD as fallback.
                _prog_block_re = re.compile(
                    r'"progressive_urls":\s*\[(.*?)\]', re.DOTALL,
                )
                _prog_entry_re = re.compile(
                    r'"progressive_url":\s*"([^"]+)"'
                    r'.*?"quality":\s*"([^"]+)"',
                    re.DOTALL,
                )
                found_progressive = False
                for block in _prog_block_re.finditer(html):
                    content = block.group(1)
                    entries: dict[str, str] = {}
                    for m in _prog_entry_re.finditer(content):
                        entries[m.group(2).upper()] = m.group(1)
                    best = entries.get("HD") or entries.get("SD")
                    if best:
                        _add("video", best)
                        found_progressive = True

                # Fallback: bare progressive_url without quality
                if not found_progressive:
                    for m in re.finditer(
                        r'"progressive_url":\s*"([^"]+)"', html
                    ):
                        _add("video", m.group(1))
                        found_progressive = True

                # ── 2. Secondary video URL patterns ──────────────
                if not found_progressive:
                    for pat in (
                        r'"playable_url_quality_hd":\s*"([^"]+)"',
                        r'"playable_url":\s*"([^"]+)"',
                        r'"browser_native_hd_url":\s*"([^"]+)"',
                        r'"browser_native_sd_url":\s*"([^"]+)"',
                    ):
                        for m in re.finditer(pat, html):
                            val = m.group(1)
                            if val and val != "null":
                                _add("video", val)

                # ── 3. Photo story images ────────────────────────
                # Story-specific photo images use type t51.71878 at
                # high resolution.  Skip anything that's a video
                # thumbnail (context contains "preferred_thumbnail"
                # or "previewImage").
                for m in re.finditer(
                    r'"image":\s*\{\s*"uri":\s*"(https?:\\?/\\?/scontent[^"]+)"',
                    html,
                ):
                    uri = m.group(1)
                    if _SKIP_RE.search(uri):
                        continue
                    # Reject video poster thumbnails by context
                    start = max(0, m.start() - 300)
                    ctx = html[start:m.start()]
                    if "preferred_thumbnail" in ctx or "previewImage" in ctx:
                        continue
                    _add("image", uri)

                # Also: "photoImage":{"uri":"…"} for explicit photo stories
                for m in re.finditer(
                    r'"photoImage"\s*:\s*\{[^}]*"uri":\s*"([^"]+)"',
                    html, re.IGNORECASE,
                ):
                    uri = m.group(1)
                    if not _SKIP_RE.search(uri):
                        _add("image", uri)

            except Exception:
                pass

            browser.close()

        logger.info("fb_story_media_found", count=len(media),
                     videos=sum(1 for k, _ in media if k == "video"),
                     images=sum(1 for k, _ in media if k == "image"))
        return media

    @staticmethod
    def _build_story_result(media: list[tuple[str, str]]) -> ScrapedResult:
        """Convert collected media tuples into a ScrapedResult."""
        variants: list[ScrapedVariant] = []
        vid_n = 0
        img_n = 0
        thumbnail = None

        for kind, url in media:
            if kind == "video":
                vid_n += 1
                variants.append(ScrapedVariant(
                    label=f"Story Video {vid_n}",
                    format="mp4", url=url,
                    has_video=True, has_audio=True,
                ))
                if not thumbnail:
                    thumbnail = url
            else:
                img_n += 1
                variants.append(ScrapedVariant(
                    label=f"Story Photo {img_n}",
                    format="jpg", url=url,
                ))
                if not thumbnail:
                    thumbnail = url

        return ScrapedResult(
            title="Facebook Story",
            thumbnail_url=thumbnail,
            content_type="story",
            variants=variants,
        )

    # ─────────────────────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_cdn_media(html: str, content_type: str) -> Optional[ScrapedResult]:
        """Extract video and image CDN URLs from raw HTML."""
        variants: list[ScrapedVariant] = []
        thumbnail = None
        seen: set[str] = set()

        # Video URLs
        for raw in re.findall(
            r"(https?://(?:video|scontent)[^\s\"'\\>]+?\.mp4[^\s\"'\\>]*)",
            html, re.IGNORECASE,
        ):
            clean = unescape(raw.replace("\\u0026", "&").replace("\\/", "/"))
            if clean not in seen:
                seen.add(clean)
                variants.append(ScrapedVariant(
                    label=f"Video {len(variants) + 1}", format="mp4",
                    url=clean, has_video=True, has_audio=True,
                ))

        # Image URLs (skip tiny/emoji/profile pics)
        for raw in re.findall(
            r"(https?://(?:scontent|external)[^\s\"'\\>]+?\.(?:jpg|jpeg|png|webp)[^\s\"'\\>]*)",
            html, re.IGNORECASE,
        ):
            clean = unescape(raw.replace("\\u0026", "&").replace("\\/", "/"))
            if clean in seen or "emoji" in clean or "static" in clean:
                continue
            # Skip small images based on dimension hints in URL
            dim = re.search(r'[sp_](\d+)x(\d+)', clean)
            if dim and max(int(dim.group(1)), int(dim.group(2))) < 400:
                continue
            seen.add(clean)
            if not thumbnail:
                thumbnail = clean
            if not variants:  # Only add images if no video found
                variants.append(ScrapedVariant(
                    label=f"Photo {len([v for v in variants if not v.has_video]) + 1}",
                    format="jpg", url=clean,
                ))

        if not variants:
            return None

        return ScrapedResult(
            title="Facebook Content", thumbnail_url=thumbnail,
            content_type=content_type, variants=variants,
        )
