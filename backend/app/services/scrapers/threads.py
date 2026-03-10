"""
Threads scraper – Meta's Threads platform (threads.net / threads.com).

Strategy priority:
  1. Threads GraphQL API   (shortcode→media_id, needs valid cookies)
  2. yt-dlp Threads URL    (no native extractor yet; for future support)
  3. yt-dlp Instagram URL  (cross-reference shortcode via IG extractors)
  4. Playwright rendering  (parse embedded CDN media URLs from rendered HTML)
  5. OG-tag fallback       (last resort from meta tags)

NOTE: Threads requires authentication for virtually all post content.
      Ensure threads_cookies.txt has fresh, valid browser-exported cookies.
"""

import json
import logging
import os
import re
import uuid
from html import unescape
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import httpx
from app.core.config import settings
from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.services.scrapers.helpers import build_ytdlp_variants, parse_og_tags
from app.utils.ytdlp_helper import extract_with_ytdlp
from app.utils.browser import get_page_content

logger = logging.getLogger(__name__)

# ── Threads API constants ────────────────────────────────────────

_THREADS_API = "https://www.threads.com/graphql/query"

# Doc IDs are loaded from settings (see config.py for defaults)

_POST_ID_RE = re.compile(r"/post/([A-Za-z0-9_-]+)")
_NUMERIC_POST_RE = re.compile(r"/t/(\d+)")
_USERNAME_RE = re.compile(r"threads\.(?:net|com)/@([A-Za-z0-9_.]+)")

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Reuse the same temp directory as other scrapers for generated files
from app.services.scrapers.scribd import PDF_DIR as _FILES_DIR


def _is_threads_profile_pic(url: str, width: int = 0, height: int = 0) -> bool:
    """Return True if the URL looks like a profile picture."""
    low = url.lower()
    if any(s in low for s in (
        "profile_pic", "/s150x150/", "/s44x44/", "/s110x110/",
        "/s320x320/", "150x150", "44x44", "110x110",
    )):
        return True
    if width and height and max(width, height) < 400:
        return True
    return False

# Base-64-like alphabet used by Instagram / Threads for shortcodes
_SHORTCODE_CHARSET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


def _shortcode_to_media_id(shortcode: str) -> str:
    """Decode a Threads/Instagram shortcode to its numeric media ID."""
    media_id = 0
    for ch in shortcode:
        media_id = media_id * 64 + _SHORTCODE_CHARSET.index(ch)
    return str(media_id)


# ── Cookie helpers ────────────────────────────────────────────────

def _get_threads_cookies_file() -> Optional[str]:
    """Resolve the Netscape cookies file for Threads."""
    if not settings.THREADS_COOKIES_FILE:
        return None
    if os.path.isfile(settings.THREADS_COOKIES_FILE):
        return settings.THREADS_COOKIES_FILE
    # Try relative to the backend root (four levels up from scrapers/__file__)
    backend_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    abs_path = os.path.join(backend_root, settings.THREADS_COOKIES_FILE)
    if os.path.isfile(abs_path):
        return abs_path
    return None


def _parse_netscape_cookies(filepath: str) -> list[dict]:
    """Parse a Netscape-format cookies.txt into a Playwright-compatible list."""
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
        logger.warning("threads_parse_cookie_err: %s", exc)
    return cookies


def _get_playwright_cookies() -> list[dict]:
    """Get Playwright-compatible cookie list for Threads."""
    cookie_file = _get_threads_cookies_file()
    if cookie_file:
        parsed = _parse_netscape_cookies(cookie_file)
        if parsed:
            logger.debug("threads_pw_cookies_from_file count=%d", len(parsed))
            return parsed
    return []


def _get_httpx_cookies() -> dict[str, str]:
    """Build a simple {name: value} dict for httpx from the cookie file."""
    cookie_file = _get_threads_cookies_file()
    if not cookie_file:
        return {}
    raw = _parse_netscape_cookies(cookie_file)
    # Prefer .threads.net domain cookies for the API
    cookies: dict[str, str] = {}
    for c in raw:
        cookies[c["name"]] = c["value"]
    return cookies


class ThreadsScraper(BaseScraper):
    platform = "threads"

    _DOMAIN_RE = re.compile(r"threads\.(?:net|com)")

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize threads.com URLs to threads.net for API/yt-dlp compatibility."""
        return url.replace("threads.com", "threads.net").replace("/media", "")

    @staticmethod
    def _get_instagram_cookies_file() -> Optional[str]:
        """Resolve the Instagram cookies file (for yt-dlp cross-reference)."""
        if not settings.INSTAGRAM_COOKIES_FILE:
            return None
        if os.path.isfile(settings.INSTAGRAM_COOKIES_FILE):
            return settings.INSTAGRAM_COOKIES_FILE
        backend_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        abs_path = os.path.join(backend_root, settings.INSTAGRAM_COOKIES_FILE)
        if os.path.isfile(abs_path):
            return abs_path
        return None

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _extract_post_shortcode(url: str) -> Optional[str]:
        m = _POST_ID_RE.search(url)
        return m.group(1) if m else None

    @staticmethod
    def _extract_numeric_id(url: str) -> Optional[str]:
        m = _NUMERIC_POST_RE.search(url)
        return m.group(1) if m else None

    @staticmethod
    def _extract_username(url: str) -> Optional[str]:
        m = _USERNAME_RE.search(url)
        return m.group(1) if m else None

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": _DESKTOP_UA,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.threads.com",
            "Referer": "https://www.threads.com/",
            "X-IG-App-ID": settings.THREADS_APP_ID,
            "X-FB-LSD": "default",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        # Inject csrftoken from cookies if available
        httpx_cookies = _get_httpx_cookies()
        if "csrftoken" in httpx_cookies:
            headers["X-CSRFToken"] = httpx_cookies["csrftoken"]
        return headers

    # ── Main entry ───────────────────────────────────────────────

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        original_url = url
        errors: list[str] = []

        # Extract shortcode early — needed by multiple strategies
        shortcode = self._extract_post_shortcode(url)

        # ── Strategy 1: Threads GraphQL API ──────────────────────
        try:
            result = await self._scrape_graphql(url, content_tab)
            if result and result.variants:
                return result
        except Exception as exc:
            errors.append(f"graphql: {exc}")
            logger.warning("Threads GraphQL failed: %s", exc)

        # ── Strategy 2: yt-dlp with Threads URL ─────────────────
        try:
            ytdlp_opts: dict = {}
            cookie_file = _get_threads_cookies_file()
            if cookie_file:
                ytdlp_opts["cookiefile"] = cookie_file
            info = await extract_with_ytdlp(url, extra_opts=ytdlp_opts)
            variants = build_ytdlp_variants(info)
            if variants:
                return ScrapedResult(
                    title=info.get("title", "Threads Post"),
                    description=info.get("description"),
                    author=info.get("uploader") or info.get("channel"),
                    thumbnail_url=info.get("thumbnail"),
                    duration_seconds=info.get("duration"),
                    content_type=(
                        "video" if any(v.has_video for v in variants) else "image"
                    ),
                    variants=variants,
                )
        except Exception as exc:
            errors.append(f"ytdlp: {exc}")

        # ── Strategy 2b: yt-dlp via Instagram URL ────────────────
        # Threads and Instagram share the same media backend;
        # yt-dlp has Instagram extractors but not Threads ones.
        if shortcode:
            for ig_path in (f"/reel/{shortcode}/", f"/p/{shortcode}/"):
                ig_url = f"https://www.instagram.com{ig_path}"
                try:
                    ig_opts: dict = {}
                    # Prefer Instagram cookies for Instagram URLs
                    ig_cookie = self._get_instagram_cookies_file()
                    if ig_cookie:
                        ig_opts["cookiefile"] = ig_cookie
                    elif cookie_file:
                        ig_opts["cookiefile"] = cookie_file
                    info = await extract_with_ytdlp(ig_url, extra_opts=ig_opts)
                    variants = build_ytdlp_variants(info)
                    if variants:
                        return ScrapedResult(
                            title=info.get("title", "Threads Post"),
                            description=info.get("description"),
                            author=info.get("uploader") or info.get("channel"),
                            thumbnail_url=info.get("thumbnail"),
                            duration_seconds=info.get("duration"),
                            content_type=(
                                "video" if any(v.has_video for v in variants) else "image"
                            ),
                            variants=variants,
                        )
                except Exception as exc:
                    errors.append(f"ytdlp_ig({ig_path}): {exc}")
                    continue

        # ── Strategy 3: Playwright page parsing ──────────────────
        pw_cookies = _get_playwright_cookies()
        html = await get_page_content(
            original_url, use_browser=True, cookies=pw_cookies or None
        )
        if html:
            # Check if we got a login/gating page (cookies invalid)
            is_login_page = "LoggedOutGating" in html or (
                'og:title' in html and 'Log in' in html[:5000]
            )
            if is_login_page:
                logger.warning(
                    "Threads returned login page — cookies may be "
                    "expired or invalid. Please re-export fresh cookies."
                )

            result = self._parse_threads_page(html)
            if result and result.variants:
                return result

            # ── Text-only fallback from Playwright HTML ──────────
            text_content = self._extract_text_from_html(html)
            if text_content and content_tab in (None, "Text"):
                author = ""
                m = re.search(r'"username"\s*:\s*"([^"]+)"', html)
                if m:
                    author = m.group(1)
                return self._build_text_result(author, text_content)

            # Strategy 4: OG-tag fallback
            result = parse_og_tags(html, "Threads Post", "other")
            if result.variants:
                # Filter out profile pics from OG tags
                filtered = [
                    v for v in result.variants
                    if not _is_threads_profile_pic(v.url)
                ]
                if filtered:
                    result.variants = filtered
                    return result
                # All variants were profile pics — this is a text-only post
                if text_content:
                    return self._build_text_result(author, text_content)

        raise ValueError(
            "Could not extract this Threads post. "
            "Threads requires authentication for most content. "
            "Please ensure your threads_cookies.txt contains fresh, "
            "valid cookies exported from your browser."
        )

    # ── Strategy 1: GraphQL API ──────────────────────────────────

    async def _scrape_graphql(
        self, url: str, content_tab: Optional[str] = None
    ) -> Optional[ScrapedResult]:
        shortcode = self._extract_post_shortcode(url)
        if not shortcode:
            return None

        # Decode shortcode to numeric post ID
        try:
            post_id = _shortcode_to_media_id(shortcode)
        except (ValueError, KeyError):
            logger.warning("Could not decode shortcode: %s", shortcode)
            return None

        # Extract LSD token from homepage
        tokens = await self._extract_graphql_tokens()
        lsd_token = tokens.get("lsd", "default")

        httpx_cookies = _get_httpx_cookies()
        csrf_token = httpx_cookies.get("csrftoken", "")

        # Build headers
        headers = self._build_headers()
        headers["X-FB-LSD"] = lsd_token
        headers["X-FB-Friendly-Name"] = "BarcelonaPostPageDirectQuery"
        headers["X-ASBD-ID"] = "359341"
        if csrf_token:
            headers["X-CSRFToken"] = csrf_token

        # Build GraphQL variables (logged-out mode works for public posts)
        variables = {
            "postID": post_id,
            "sort_order": "TOP",
            "__relay_internal__pv__BarcelonaCanSeeSponsoredContentrelayprovider": False,
            "__relay_internal__pv__BarcelonaHasCommunitiesrelayprovider": True,
            "__relay_internal__pv__BarcelonaHasCommunityTopContributorsrelayprovider": False,
            "__relay_internal__pv__BarcelonaHasDearAlgoConsumptionrelayprovider": True,
            "__relay_internal__pv__BarcelonaHasDearAlgoWebProductionrelayprovider": False,
            "__relay_internal__pv__BarcelonaHasDeepDiverelayprovider": False,
            "__relay_internal__pv__BarcelonaHasDisplayNamesrelayprovider": False,
            "__relay_internal__pv__BarcelonaHasEventBadgerelayprovider": False,
            "__relay_internal__pv__BarcelonaHasGameScoreSharerelayprovider": True,
            "__relay_internal__pv__BarcelonaHasGhostPostConsumptionrelayprovider": True,
            "__relay_internal__pv__BarcelonaHasGhostPostEmojiActivationrelayprovider": False,
            "__relay_internal__pv__BarcelonaHasGhostPostNullStateStringrelayprovider": False,
            "__relay_internal__pv__BarcelonaHasMusicrelayprovider": False,
            "__relay_internal__pv__BarcelonaHasPermalinkInlineExpansionrelayprovider": True,
            "__relay_internal__pv__BarcelonaHasPodcastConsumptionrelayprovider": True,
            "__relay_internal__pv__BarcelonaHasPostAuthorNotifControlsrelayprovider": True,
            "__relay_internal__pv__BarcelonaHasSelfThreadCountrelayprovider": False,
            "__relay_internal__pv__BarcelonaHasSpoilerStylingInforelayprovider": False,
            "__relay_internal__pv__BarcelonaHasTopicTagsrelayprovider": True,
            "__relay_internal__pv__BarcelonaImplicitTrendsGKrelayprovider": False,
            "__relay_internal__pv__BarcelonaInlineComposerEnabledrelayprovider": False,
            "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": False,
            "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": False,
            "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": False,
            "__relay_internal__pv__BarcelonaIsReplyApprovalEnabledrelayprovider": False,
            "__relay_internal__pv__BarcelonaIsReplyApprovalsConsumptionEnabledrelayprovider": False,
            "__relay_internal__pv__BarcelonaIsSearchDiscoveryEnabledrelayprovider": False,
            "__relay_internal__pv__BarcelonaOptionalCookiesEnabledrelayprovider": True,
            "__relay_internal__pv__BarcelonaQuotedPostUFIEnabledrelayprovider": True,
            "__relay_internal__pv__BarcelonaShouldShowFediverseM075Featuresrelayprovider": False,
            "__relay_internal__pv__BarcelonaShouldShowFediverseM1Featuresrelayprovider": False,
            "__relay_internal__pv__IsTagIndicatorEnabledrelayprovider": True,
        }

        # Build form data
        data = {
            "__a": "1",
            "__user": "0",
            "av": "0",
            "lsd": lsd_token,
            "jazoest": "22518",
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": "BarcelonaPostPageDirectQuery",
            "doc_id": settings.THREADS_POST_DOC_ID,
            "variables": json.dumps(variables),
            "server_timestamps": "true",
            "__comet_req": "122",
            "dpr": "1",
        }

        async with httpx.AsyncClient(
            timeout=20, follow_redirects=True, cookies=httpx_cookies or None
        ) as client:
            resp = await client.post(_THREADS_API, headers=headers, data=data)

        if resp.status_code != 200:
            logger.warning("Threads API HTTP %s", resp.status_code)
            return None

        body = resp.text
        if body.startswith("for (;;);"):
            body = body[len("for (;;);"):]

        try:
            response_data = json.loads(body)
        except json.JSONDecodeError:
            logger.warning("Threads API returned non-JSON response")
            return None

        # Check for API error responses
        if "errors" in response_data:
            for err in response_data["errors"]:
                logger.warning("Threads API error: %s", err.get("message", ""))
            return None
        if "error" in response_data:
            logger.warning("Threads API error %s: %s",
                           response_data.get("error"),
                           response_data.get("errorSummary", ""))
            return None

        return self._parse_graphql_response(response_data, content_tab)

    async def _extract_graphql_tokens(self) -> dict[str, str]:
        """Fetch the Threads homepage to extract GraphQL tokens (lsd, fb_dtsg, av, etc.)."""
        tokens: dict[str, str] = {}
        try:
            httpx_cookies = _get_httpx_cookies()
            async with httpx.AsyncClient(
                timeout=15, follow_redirects=True,
                headers={"User-Agent": _DESKTOP_UA},
                cookies=httpx_cookies or None,
            ) as client:
                resp = await client.get("https://www.threads.com/")
                html = resp.text

            # LSD token
            m = re.search(r'"LSD",\[\],\{"token":"([^"]+)"', html)
            if m:
                tokens["lsd"] = m.group(1)
            if not tokens.get("lsd"):
                m = re.search(r'name="lsd"\s+value="([^"]+)"', html)
                if m:
                    tokens["lsd"] = m.group(1)

            # fb_dtsg (critical for authenticated GraphQL)
            m = re.search(r'"DTSGInitialData",\[\],\{"token":"([^"]+)"', html)
            if m:
                tokens["fb_dtsg"] = m.group(1)
            if not tokens.get("fb_dtsg"):
                m = re.search(r'"dtsg":\{"token":"([^"]+)"', html)
                if m:
                    tokens["fb_dtsg"] = m.group(1)

            # Actor viewer ID (FBID)
            m = re.search(r'"actorID"\s*:\s*"(\d+)"', html)
            if m:
                tokens["av"] = m.group(1)

            # Haste session ID
            m = re.search(r'"hsi"\s*:\s*"(\d+)"', html)
            if m:
                tokens["hsi"] = m.group(1)

            # Server revision
            m = re.search(r'"server_revision"\s*:\s*(\d+)', html)
            if m:
                tokens["rev"] = m.group(1)
            if not tokens.get("rev"):
                m = re.search(r'"__spin_r"\s*:\s*(\d+)', html)
                if m:
                    tokens["rev"] = m.group(1)

            # Spin timestamp
            m = re.search(r'"__spin_t"\s*:\s*(\d+)', html)
            if m:
                tokens["spin_t"] = m.group(1)

        except Exception as exc:
            logger.debug("Failed to extract GraphQL tokens: %s", exc)

        return tokens

    def _parse_graphql_response(
        self, data: dict, content_tab: Optional[str] = None
    ) -> Optional[ScrapedResult]:
        """Parse Threads GraphQL API response to extract media."""
        try:
            # Response format: data.data.edges[].node.thread_items[].post
            inner = data.get("data", {}).get("data")
            if isinstance(inner, dict):
                edges = inner.get("edges", [])
                for edge in edges:
                    node = edge.get("node", {})
                    thread_items = node.get("thread_items", [])
                    if thread_items:
                        post = thread_items[0].get("post", {})
                        result = self._extract_media_from_post(post, content_tab)
                        if result:
                            return result

            # Fallback: older containing_thread format
            containing_thread = (
                data.get("data", {})
                .get("data", {})
                .get("containing_thread", {})
            )
            thread_items = containing_thread.get("thread_items", [])
            if not thread_items:
                thread_items = (
                    data.get("data", {})
                    .get("containing_thread", {})
                    .get("thread_items", [])
                )

            if thread_items:
                post = thread_items[0].get("post", {})
                return self._extract_media_from_post(post, content_tab)

            return None

        except Exception as exc:
            logger.warning("Failed to parse Threads GraphQL response: %s", exc)
            return None

    def _extract_media_from_post(
        self, post: dict, content_tab: Optional[str] = None
    ) -> Optional[ScrapedResult]:
        """Extract media variants from a Threads post object."""
        variants: list[ScrapedVariant] = []
        thumbnail: Optional[str] = None

        user = post.get("user", {})
        author = user.get("username") or user.get("full_name") or ""
        caption_data = post.get("caption")
        text = caption_data.get("text", "") if isinstance(caption_data, dict) else ""
        title = f"@{author}: {text[:80]}" if author else (text[:100] or "Threads Post")

        # Check for carousel (multiple media items)
        carousel = post.get("carousel_media") or []
        media_items = carousel if carousel else [post]

        has_video_post = False  # Track whether any item is a video
        has_real_media = False  # Track whether any item has real (non-profile) media

        for item in media_items:
            media_type = item.get("media_type")
            # media_type: 1 = photo, 2 = video, 8 = carousel

            # Extract thumbnail — skip profile pics
            image_versions = item.get("image_versions2", {})
            candidates = image_versions.get("candidates", [])
            good_candidates = [
                c for c in candidates
                if c.get("url") and not _is_threads_profile_pic(
                    c["url"], c.get("width", 0), c.get("height", 0)
                )
            ]
            if good_candidates and not thumbnail:
                thumbnail = good_candidates[0].get("url")
                has_real_media = True

            if media_type == 2:
                # Video
                has_video_post = True
                if content_tab == "Images":
                    continue

                video_versions = item.get("video_versions", [])
                seen_res: set[str] = set()
                for vid in video_versions:
                    vid_url = vid.get("url")
                    if not vid_url:
                        continue
                    width = vid.get("width", 0)
                    height = vid.get("height", 0)
                    res_key = f"{width}x{height}"
                    if res_key in seen_res:
                        continue
                    seen_res.add(res_key)
                    has_real_media = True

                    if height >= 1080:
                        label = "1080p"
                    elif height >= 720:
                        label = "720p"
                    elif height >= 480:
                        label = "480p"
                    elif height >= 360:
                        label = "360p"
                    else:
                        label = f"{height}p" if height else "Video"

                    variants.append(
                        ScrapedVariant(
                            label=label,
                            format="mp4",
                            url=vid_url,
                            has_video=True,
                            has_audio=True,
                        )
                    )

                # Only add the thumbnail if we actually got video variants too
                has_real_video = any(v.has_video for v in variants)
                if has_real_video and good_candidates and content_tab != "Videos":
                    best_img = good_candidates[0].get("url")
                    if best_img:
                        variants.append(
                            ScrapedVariant(
                                label="Thumbnail",
                                format="jpg",
                                url=best_img,
                            )
                        )

            else:
                # Photo (media_type 1 or anything else)
                if content_tab == "Videos":
                    continue

                if good_candidates:
                    # Pick the best (largest) image
                    best = max(good_candidates, key=lambda c: c.get("width", 0) * c.get("height", 0))
                    img_url = best.get("url")
                    if img_url:
                        width = best.get("width", 0)
                        height = best.get("height", 0)
                        label = f"Image {width}x{height}" if width and height else "Original"
                        variants.append(
                            ScrapedVariant(
                                label=label,
                                format="jpg",
                                url=img_url,
                            )
                        )

        # If this is a video post but we got no actual video URLs,
        # return None so the caller falls through to yt-dlp / Playwright
        if has_video_post and not any(v.has_video for v in variants):
            logger.debug("Video post detected but no video URLs extracted — falling through")
            return None

        # ── Text-only post handling ──────────────────────────────
        # If no real media variants were found but we have text content,
        # generate a downloadable text file
        if not variants and text.strip():
            return self._build_text_result(author, text, thumbnail)

        if not variants:
            return None

        content_type = "video" if any(v.has_video for v in variants) else "image"
        return ScrapedResult(
            title=title,
            description=text,
            author=author,
            thumbnail_url=thumbnail,
            content_type=content_type,
            variants=variants,
        )

    # ── Private helpers ──────────────────────────────────────────

    @staticmethod
    def _build_text_result(
        author: str, text: str, thumbnail: Optional[str] = None
    ) -> ScrapedResult:
        """Create a downloadable .txt file for a text-only Threads post."""
        filename = f"threads_text_{uuid.uuid4().hex[:12]}.txt"
        filepath = _FILES_DIR / filename
        _FILES_DIR.mkdir(parents=True, exist_ok=True)
        filepath.write_text(text, encoding="utf-8")
        logger.info("Saved text-only post to %s", filepath)

        title = f"@{author}" if author else "Threads Post"
        return ScrapedResult(
            title=title,
            description=text,
            author=author,
            thumbnail_url=thumbnail,
            content_type="text",
            variants=[
                ScrapedVariant(
                    label="Text Post",
                    format="txt",
                    url=f"/api/files/{filename}",
                )
            ],
        )

    @staticmethod
    def _extract_text_from_html(html: str) -> Optional[str]:
        """Try to extract post text content from rendered Threads HTML."""
        # Look for caption text in embedded JSON
        m = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.){10,})"', html)
        if m:
            try:
                return json.loads(f'"{m.group(1)}"')
            except (json.JSONDecodeError, ValueError):
                return m.group(1)
        # Look for og:description as a last resort
        m = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', html)
        if m:
            text = unescape(m.group(1))
            if len(text) > 10:
                return text
        return None

    @staticmethod
    def _parse_threads_page(html: str) -> Optional[ScrapedResult]:
        """Parse the rendered Threads page for video / image media."""
        variants: list[ScrapedVariant] = []
        thumbnail: Optional[str] = None

        # Try to extract structured data from embedded JSON in script tags
        result = ThreadsScraper._try_parse_embedded_json(html)
        if result and result.variants:
            return result

        # Fallback: regex CDN URL extraction
        # ── Videos ───────────────────────────────────────────────
        seen: set[str] = set()

        # 1) URLs with explicit .mp4 / .webm extensions
        video_urls = re.findall(
            r"(https://(?:scontent|video)[^\s\"'\\]+\.(?:mp4|webm)[^\s\"'\\]*)",
            html,
        )
        # 2) <video> tag src attributes (Playwright-rendered HTML)
        video_src = re.findall(
            r'<video[^>]+\bsrc=["\']([^"\'>]+)["\']',
            html,
            re.IGNORECASE,
        )
        # 3) CDN video paths – t50 and t42 are videos; t51 is images (skip!)
        cdn_videos = re.findall(
            r'(https://(?:scontent|video)[^\s"\'\\">]+/v/t(?:50|42|16)[^\s"\'\\">]+)',
            html,
        )
        # 4) "video_url" values from embedded JSON
        json_video_urls = re.findall(
            r'"video_url"\s*:\s*"(https?://[^"]+)"',
            html,
        )

        for raw in (video_urls + video_src + cdn_videos + json_video_urls)[:10]:
            clean = unescape(raw.replace("\\u0026", "&").replace("\\/", "/"))
            if clean not in seen:
                seen.add(clean)
                variants.append(
                    ScrapedVariant(
                        label="Video",
                        format="mp4",
                        url=clean,
                        has_video=True,
                        has_audio=True,
                    )
                )

        # ── Images ───────────────────────────────────────────────
        image_urls = re.findall(
            r"(https://(?:scontent|instagram)[^\s\"'\\]+\.(?:jpg|jpeg|png|webp)[^\s\"'\\]*)",
            html,
        )
        for raw in image_urls:
            clean = unescape(raw.replace("\\u0026", "&").replace("\\/", "/"))
            # Skip tiny thumbnails / profile pics
            if clean in seen or _is_threads_profile_pic(clean):
                continue
            seen.add(clean)
            if not thumbnail:
                thumbnail = clean
            variants.append(
                ScrapedVariant(label="Image", format="jpg", url=clean)
            )

        if not variants:
            return None

        content_type = "video" if any(v.has_video for v in variants) else "image"
        return ScrapedResult(
            title="Threads Post",
            thumbnail_url=thumbnail,
            content_type=content_type,
            variants=variants,
        )

    @staticmethod
    def _try_parse_embedded_json(html: str) -> Optional[ScrapedResult]:
        """Try to find and parse embedded post JSON from the page source."""
        # Threads embeds post data in script tags as JSON
        # Look for patterns like "video_versions" or "image_versions2"
        patterns = [
            r'{"post_id".*?"video_versions"\s*:\s*\[.*?\].*?}',
            r'{"media_id".*?"video_versions"\s*:\s*\[.*?\].*?}',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html, re.DOTALL)
            for match in matches[:1]:
                try:
                    data = json.loads(match)
                    scraper = ThreadsScraper()
                    result = scraper._extract_media_from_post(data)
                    if result and result.variants:
                        return result
                except (json.JSONDecodeError, Exception):
                    continue

        # Also try to extract video_url directly from embedded JSON
        video_url_match = re.search(
            r'"video_url"\s*:\s*"(https?://[^"]+)"', html
        )
        if video_url_match:
            video_url = unescape(
                video_url_match.group(1)
                .replace("\\u0026", "&")
                .replace("\\/", "/")
            )
            # Try to get a thumbnail too
            thumb_match = re.search(
                r'"image_versions2".*?"url"\s*:\s*"(https?://[^"]+)"', html
            )
            thumb_url = None
            if thumb_match:
                thumb_url = unescape(
                    thumb_match.group(1)
                    .replace("\\u0026", "&")
                    .replace("\\/", "/")
                )
            return ScrapedResult(
                title="Threads Post",
                thumbnail_url=thumb_url,
                content_type="video",
                variants=[
                    ScrapedVariant(
                        label="Video",
                        format="mp4",
                        url=video_url,
                        has_video=True,
                        has_audio=True,
                    )
                ],
            )

        return None
