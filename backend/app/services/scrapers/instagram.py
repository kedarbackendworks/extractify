"""
Instagram scraper – authenticated extraction for Reels, Stories,
Photos, Feed, IGTV, and Live content.

Strategies:
  Stories  → Authenticated API → yt-dlp (cookies) → Playwright (cookies)
  Photos   → GraphQL API → embed page → yt-dlp → Playwright (cookies)
  Reels    → yt-dlp (cookies) → embed page → Playwright
"""

import json
import os
import re
import tempfile
import structlog
from html import unescape
from typing import Optional

import httpx
from app.core.config import settings
from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.services.scrapers.helpers import build_ytdlp_variants, parse_og_tags
from app.utils.ytdlp_helper import extract_with_ytdlp
from app.utils.browser import get_page_content
from app.utils.http_client import get_http_client

logger = structlog.get_logger()

# ── Constants ────────────────────────────────────────────────────

_MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)
_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_SQUARE_SIZE_RE = re.compile(r'/s(\d+)x(\d+)/')




# ─────────────────────────────────────────────────────────────────
#  Session cookie helpers
# ─────────────────────────────────────────────────────────────────

def _has_ig_session() -> bool:
    return bool(settings.INSTAGRAM_SESSION_ID)


def _get_ig_cookies() -> dict[str, str]:
    cookies: dict[str, str] = {}
    if settings.INSTAGRAM_SESSION_ID:
        cookies["sessionid"] = settings.INSTAGRAM_SESSION_ID
    if settings.INSTAGRAM_CSRF_TOKEN:
        cookies["csrftoken"] = settings.INSTAGRAM_CSRF_TOKEN
    if settings.INSTAGRAM_DS_USER_ID:
        cookies["ds_user_id"] = settings.INSTAGRAM_DS_USER_ID
    return cookies


def _get_ig_auth_headers(*, mobile: bool = False) -> dict[str, str]:
    ua = _MOBILE_UA if mobile else _DESKTOP_UA
    headers = {
        "User-Agent": ua,
        "X-IG-App-ID": settings.IG_MOBILE_APP_ID if mobile else settings.IG_APP_ID,
        "X-IG-WWW-Claim": "0",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.instagram.com/",
        "Origin": "https://www.instagram.com",
    }
    if settings.INSTAGRAM_CSRF_TOKEN:
        headers["X-CSRFToken"] = settings.INSTAGRAM_CSRF_TOKEN
    return headers


def _get_playwright_cookies() -> list[dict]:
    return [
        {"name": n, "value": v, "domain": ".instagram.com", "path": "/"}
        for n, v in _get_ig_cookies().items()
    ]


def _get_ig_cookies_file() -> Optional[str]:
    """Resolve or auto-generate a Netscape cookies file for yt-dlp."""
    if settings.INSTAGRAM_COOKIES_FILE:
        if os.path.isfile(settings.INSTAGRAM_COOKIES_FILE):
            return settings.INSTAGRAM_COOKIES_FILE
        abs_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            settings.INSTAGRAM_COOKIES_FILE,
        )
        if os.path.isfile(abs_path):
            return abs_path

    if settings.YTDLP_COOKIES_FILE and os.path.isfile(settings.YTDLP_COOKIES_FILE):
        return settings.YTDLP_COOKIES_FILE

    if settings.INSTAGRAM_SESSION_ID:
        try:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix="_ig_cookies.txt",
                delete=False, prefix="extractify_",
            )
            tmp.write("# Netscape HTTP Cookie File\n")
            for name, value in _get_ig_cookies().items():
                tmp.write(f".instagram.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n")
            tmp.close()
            return tmp.name
        except Exception as exc:
            logger.debug("ig_temp_cookie_file_error", error=str(exc))
    return None


def _is_profile_pic(url: str, width: int = 0, height: int = 0, *, story_context: bool = False) -> bool:
    """Return True if the URL looks like a profile picture rather than story media."""
    low = url.lower()
    if "profile_pic" in low:
        return True
    # Square-crop size indicator in CDN path — only small squares are profile pics.
    # Large squares (640x640, 1080x1080) are legitimate post/story images.
    m = _SQUARE_SIZE_RE.search(low)
    if m and m.group(1) == m.group(2):
        dim = int(m.group(1))
        if dim <= 320:
            return True
    # Instagram CDN path segment for profile pictures
    if "/t51.2885-19/" in low:
        return True
    # Very small images are almost certainly avatars / thumbnails
    if width and height and max(width, height) < 400:
        return True
    # In story context, small approximately-square images are profile pictures.
    # Large squares (640x640, 1080x1080) can be legitimate story content —
    # not all stories are portrait 9:16.  Only flag small ones.
    if story_context and width and height:
        ratio = width / height
        if 0.8 <= ratio <= 1.25 and max(width, height) <= 500:
            return True
    return False


def _cdn_filename(url: str) -> str:
    """Extract the filename from an Instagram CDN URL for comparison."""
    if not url:
        return ""
    return url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]


def _user_pp_filename(item: dict) -> str:
    """Extract profile pic CDN filename from a story item's user data."""
    pp_url = item.get("user", {}).get("profile_pic_url", "")
    return _cdn_filename(pp_url)


class InstagramScraper(BaseScraper):
    platform = "instagram"
    _DOMAIN_RE = re.compile(r"(instagram\.com|instagr\.am)")

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        if content_tab == "Stories" or "/stories/" in url:
            return await self._scrape_story(url)
        if (
            content_tab in ("Reels", "IGTV", "Feed", "Live")
            or "/reel/" in url
            or "/tv/" in url
        ):
            try:
                return await self._scrape_video(url)
            except Exception:
                return await self._scrape_post(url)
        if content_tab == "Photos" or "/p/" in url:
            return await self._scrape_post(url)
        try:
            return await self._scrape_video(url)
        except Exception:
            return await self._scrape_post(url)

    # ─────────────────────────────────────────────────────────────
    #  Core extraction methods
    # ─────────────────────────────────────────────────────────────

    async def _scrape_video(self, url: str) -> ScrapedResult:
        """yt-dlp for video content (reels, IGTV, feed videos)."""
        extra_opts: dict = {}
        cookie_file = _get_ig_cookies_file()
        if cookie_file:
            extra_opts["cookiefile"] = cookie_file

        info = await extract_with_ytdlp(url, extra_opts=extra_opts or None)
        variants = build_ytdlp_variants(info)
        if not variants:
            raise ValueError("yt-dlp returned no usable formats")
        return ScrapedResult(
            title=info.get("title"),
            description=info.get("description"),
            author=info.get("uploader") or info.get("channel"),
            thumbnail_url=info.get("thumbnail"),
            duration_seconds=info.get("duration"),
            content_type="reel" if "/reel/" in url else "video",
            variants=variants,
        )

    async def _scrape_story(self, url: str) -> ScrapedResult:
        """
        Stories extraction.
        1. Authenticated media info API
        2. Authenticated story feed API (mobile + web)
        3. yt-dlp with cookies
        4. Playwright with cookies
        """
        username, story_id = self._parse_story_url(url)
        errors: list[str] = []
        image_fallback: Optional[ScrapedResult] = None
        has_session = _has_ig_session()

        if has_session:
            # A1: Direct media info API
            if story_id:
                try:
                    result = await self._try_media_info_api(story_id, username)
                    if result and result.variants:
                        if any(v.has_video for v in result.variants):
                            return result
                        if not image_fallback:
                            image_fallback = result
                except Exception as exc:
                    errors.append(f"media_info: {exc}")

            # A2 + A3: Story API (mobile, then web)
            if username:
                for mobile in (True, False):
                    try:
                        result = await self._try_story_api(username, story_id, mobile=mobile)
                        if result and result.variants:
                            return result
                    except Exception as exc:
                        errors.append(f"story_api_{'mobile' if mobile else 'web'}: {exc}")

        # B1: yt-dlp with cookies file
        cookie_file = _get_ig_cookies_file()
        if cookie_file:
            try:
                info = await extract_with_ytdlp(url, extra_opts={"cookiefile": cookie_file})
                variants = build_ytdlp_variants(info)
                if variants:
                    return ScrapedResult(
                        title=info.get("title", "Instagram Story"),
                        author=info.get("uploader") or username,
                        thumbnail_url=info.get("thumbnail"),
                        duration_seconds=info.get("duration"),
                        content_type="story",
                        variants=variants,
                    )
            except Exception as exc:
                errors.append(f"ytdlp: {exc}")

        # B2: Playwright with cookies
        try:
            pw_cookies = _get_playwright_cookies() if has_session else None
            result = await self._playwright_extract(url, "story", cookies=pw_cookies)
            if result and result.variants:
                return result
        except Exception as exc:
            errors.append(f"playwright: {exc}")

        if image_fallback and image_fallback.variants:
            return image_fallback

        error_msg = (
            "Could not extract this Instagram story. "
            "It may be private, expired, or from a restricted account."
        )
        if not has_session:
            error_msg += (
                " TIP: Configure INSTAGRAM_SESSION_ID in .env to enable "
                "authenticated downloads for stories."
            )
        logger.error("ig_story_failed", url=url[:100], errors="; ".join(str(e)[:60] for e in errors[:6]))
        raise ValueError(error_msg)

    async def _scrape_post(self, url: str) -> ScrapedResult:
        """
        Photo / carousel post extraction.
        1. GraphQL API (carousel support)
        2. Embed page
        3. yt-dlp with cookies
        4. Playwright with cookies
        """
        shortcode = self._extract_shortcode(url)
        has_session = _has_ig_session()

        # 1: GraphQL API
        if has_session and shortcode:
            try:
                result = await self._try_graphql_post(shortcode)
                if result and result.variants:
                    return result
            except Exception:
                pass

        # 2: Embed page
        if shortcode:
            try:
                result = await self._scrape_embed(shortcode)
                if result.variants:
                    return result
            except Exception:
                pass

        # 3: yt-dlp with cookies
        cookie_file = _get_ig_cookies_file()
        if cookie_file:
            try:
                info = await extract_with_ytdlp(url, extra_opts={"cookiefile": cookie_file})
                variants = build_ytdlp_variants(info)
                if variants:
                    return ScrapedResult(
                        title=info.get("title"),
                        description=info.get("description"),
                        author=info.get("uploader") or info.get("channel"),
                        thumbnail_url=info.get("thumbnail"),
                        duration_seconds=info.get("duration"),
                        content_type="image",
                        variants=variants,
                    )
            except Exception:
                pass

        # 4: Playwright
        try:
            pw_cookies = _get_playwright_cookies() if has_session else None
            result = await self._playwright_extract(url, "image", cookies=pw_cookies)
            if result and result.variants:
                return result
        except Exception:
            pass

        # Final: Playwright OG tags
        html = await get_page_content(
            url, use_browser=True,
            cookies=_get_playwright_cookies() if has_session else None,
        )
        if html:
            result = parse_og_tags(html, "Instagram Post", "image")
            if result.variants:
                return result

        error_msg = "Could not extract this Instagram post. It may be private or require authentication."
        if not has_session:
            error_msg += " TIP: Configure INSTAGRAM_SESSION_ID in .env."
        raise ValueError(error_msg)

    # ─────────────────────────────────────────────────────────────
    #  Authenticated API methods
    # ─────────────────────────────────────────────────────────────

    async def _try_media_info_api(
        self, media_id: str, author: Optional[str] = None, *, is_story: bool = True,
    ) -> Optional[ScrapedResult]:
        """Query /api/v1/media/{id}/info/ with session cookies."""
        cookies = _get_ig_cookies()
        if not cookies.get("sessionid"):
            return None

        for host in ("i.instagram.com", "www.instagram.com"):
            try:
                headers = _get_ig_auth_headers(mobile=(host == "i.instagram.com"))
                api_url = f"https://{host}/api/v1/media/{media_id}/info/"
                client = get_http_client()
                resp = await client.get(api_url, headers=headers, cookies=cookies)
                if resp.status_code != 200:
                    continue
                data = resp.json()

                items = data.get("items", [])
                if not items:
                    continue

                item = items[0]
                pp_name = _user_pp_filename(item)

                # ── Carousel post (multiple images/videos) ──────────
                carousel_media = item.get("carousel_media", [])
                if not is_story and carousel_media:
                    variants: list[ScrapedVariant] = []
                    thumbnail = None
                    for idx, cm in enumerate(carousel_media, 1):
                        # Video in carousel
                        for vid in cm.get("video_versions", []):
                            if vid.get("url"):
                                h = vid.get("height", 0)
                                variants.append(ScrapedVariant(
                                    label=f"Video {idx}" + (f" {h}p" if h else ""),
                                    format="mp4", url=vid["url"],
                                    has_video=True, has_audio=True,
                                ))
                                break  # best video version
                        # Image in carousel (only if no video for this item)
                        if not cm.get("video_versions"):
                            candidates = cm.get("image_versions2", {}).get("candidates", [])
                            good = [
                                c for c in candidates
                                if c.get("url")
                                and not _is_profile_pic(c["url"], c.get("width", 0), c.get("height", 0))
                                and not (pp_name and _cdn_filename(c["url"]) == pp_name)
                            ]
                            if good:
                                best = max(good, key=lambda c: c.get("width", 0) * c.get("height", 0))
                                if not thumbnail:
                                    thumbnail = best["url"]
                                variants.append(ScrapedVariant(
                                    label=f"Photo {idx}", format="jpg",
                                    url=best["url"],
                                ))
                    if variants:
                        logger.info("ig_media_info_carousel", host=host, count=len(variants))
                        return ScrapedResult(
                            title="Instagram Post",
                            author=author or item.get("user", {}).get("username"),
                            thumbnail_url=thumbnail,
                            content_type="video" if any(v.has_video for v in variants) else "image",
                            variants=variants,
                        )

                # ── Single media item ───────────────────────────────
                # For stories, check for inner reshared media
                if is_story:
                    inner = self._extract_inner_story_media(item)
                    is_direct = inner is None
                    if inner:
                        item = inner
                else:
                    is_direct = False

                variants: list[ScrapedVariant] = []
                thumbnail = None

                for vid in item.get("video_versions", []):
                    if vid.get("url") and not _is_profile_pic(vid["url"], story_context=is_direct):
                        h = vid.get("height", 0)
                        variants.append(ScrapedVariant(
                            label=f"Video {h}p" if h else "Video",
                            format="mp4", url=vid["url"],
                            has_video=True, has_audio=True,
                        ))

                for c in item.get("image_versions2", {}).get("candidates", []):
                    c_url = c.get("url", "")
                    c_w = c.get("width", 0)
                    c_h = c.get("height", 0)
                    if not c_url or _is_profile_pic(c_url, c_w, c_h, story_context=is_direct):
                        logger.debug("ig_filtered_as_profile_pic", url=c_url[:80], w=c_w, h=c_h)
                        continue
                    if pp_name and _cdn_filename(c_url) == pp_name:
                        continue
                    if not thumbnail:
                        thumbnail = c_url
                    if not variants:
                        variants.append(ScrapedVariant(
                            label=f"Photo {c_h}p" if c_h else "Photo",
                            format="jpg", url=c_url,
                        ))

                if variants:
                    title = "Instagram Story" if is_story else "Instagram Post"
                    ctype = "story" if is_story else (
                        "video" if any(v.has_video for v in variants) else "image"
                    )
                    logger.info("ig_media_info_success", host=host, is_story=is_story)
                    return ScrapedResult(
                        title=title,
                        author=author or item.get("user", {}).get("username"),
                        thumbnail_url=thumbnail,
                        content_type=ctype, variants=variants,
                    )
            except Exception as exc:
                logger.debug("ig_media_info_error", host=host, error=str(exc)[:80])
        return None

    async def _try_story_api(
        self, username: str, story_id: Optional[str], *, mobile: bool = True,
    ) -> Optional[ScrapedResult]:
        """Fetch stories via API with session cookies."""
        cookies = _get_ig_cookies()
        if not cookies.get("sessionid"):
            return None

        headers = _get_ig_auth_headers(mobile=mobile)
        user_id = await self._resolve_user_id(username)
        if not user_id:
            return None

        base = "https://i.instagram.com" if mobile else "https://www.instagram.com"
        endpoints = [
            f"{base}/api/v1/feed/user/{user_id}/story/",
            f"{base}/api/v1/feed/reels_media/?reel_ids={user_id}",
        ]

        data: dict = {}
        client = get_http_client()
        for ep in endpoints:
            try:
                resp = await client.get(ep, headers=headers, cookies=cookies)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("reel") or data.get("reels_media") or data.get("reels"):
                        break
                    data = {}
            except Exception:
                pass

        if not data:
            return None

        reel = data.get("reel")
        items = reel.get("items", []) if reel else self._parse_reels_items(data, user_id)
        return self._build_story_result(username, story_id, items)

    async def _resolve_user_id(self, username: str) -> Optional[str]:
        """Resolve username → numeric user ID."""
        cookies = _get_ig_cookies()
        headers = _get_ig_auth_headers()

        try:
            url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
            client = get_http_client()
            resp = await client.get(url, headers=headers, cookies=cookies)
            if resp.status_code == 200:
                data = resp.json()
                user = data.get("data", {}).get("user") or data.get("user")
                if user:
                    return str(user.get("id") or user.get("pk") or "")
        except Exception:
            pass

        try:
            client = get_http_client()
            resp = await client.get(
                f"https://www.instagram.com/{username}/",
                headers={"User-Agent": _DESKTOP_UA},
                cookies=cookies,
            )
            m = re.search(r'"profilePage_(\d+)"', resp.text)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None

    async def _try_graphql_post(self, shortcode: str) -> Optional[ScrapedResult]:
        """GraphQL API for full carousel support."""
        cookies = _get_ig_cookies()
        if not cookies.get("sessionid"):
            return None

        headers = _get_ig_auth_headers()

        # Try media info first (with is_story=False for correct filtering)
        media_id = self._shortcode_to_media_id(shortcode)
        if media_id:
            try:
                result = await self._try_media_info_api(str(media_id), is_story=False)
                if result and result.variants:
                    return result
            except Exception:
                pass

        # GraphQL
        variables = json.dumps({
            "shortcode": shortcode,
            "child_comment_count": 0,
            "fetch_comment_count": 0,
            "parent_comment_count": 0,
            "has_threaded_comments": False,
        })
        graphql_url = (
            f"https://www.instagram.com/graphql/query/"
            f"?query_hash={settings.IG_GRAPHQL_POST_HASH}&variables={variables}"
        )

        try:
            client = get_http_client()
            resp = await client.get(graphql_url, headers=headers, cookies=cookies)
            if resp.status_code != 200:
                return None
            data = resp.json()
        except Exception:
            return None

        media = data.get("data", {}).get("shortcode_media")
        if not media:
            return None

        variants: list[ScrapedVariant] = []
        thumbnail = None
        author = media.get("owner", {}).get("username")

        edges = media.get("edge_media_to_caption", {}).get("edges", [])
        title = edges[0].get("node", {}).get("text", "")[:120] if edges else ""

        sidecar = media.get("edge_sidecar_to_children", {}).get("edges", [])
        if sidecar:
            for idx, edge in enumerate(sidecar, 1):
                node = edge.get("node", {})
                if node.get("is_video") and node.get("video_url"):
                    variants.append(ScrapedVariant(
                        label=f"Video {idx}", format="mp4",
                        url=node["video_url"], has_video=True, has_audio=True,
                    ))
                elif node.get("display_url"):
                    if not thumbnail:
                        thumbnail = node["display_url"]
                    variants.append(ScrapedVariant(
                        label=f"Photo {idx}", format="jpg",
                        url=node["display_url"],
                    ))
        else:
            if media.get("is_video") and media.get("video_url"):
                variants.append(ScrapedVariant(
                    label="Video", format="mp4",
                    url=media["video_url"], has_video=True, has_audio=True,
                ))
            if media.get("display_url"):
                thumbnail = media["display_url"]
                if not media.get("is_video"):
                    variants.append(ScrapedVariant(
                        label="Photo", format="jpg", url=media["display_url"],
                    ))

        if not variants:
            return None

        return ScrapedResult(
            title=title or "Instagram Post", author=author,
            thumbnail_url=thumbnail,
            content_type="video" if any(v.has_video for v in variants) else "image",
            variants=variants,
        )

    # ─────────────────────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_reels_items(data: dict, user_id: str) -> list[dict]:
        reels = data.get("reels_media", [])
        if reels:
            return reels[0].get("items", [])
        reels_dict = data.get("reels", {})
        if isinstance(reels_dict, dict) and str(user_id) in reels_dict:
            return reels_dict[str(user_id)].get("items", [])
        return []

    @staticmethod
    def _extract_inner_story_media(item: dict) -> Optional[dict]:
        """If a story item reshares/mentions another post, extract the inner media.

        Instagram wraps the original content in fields like ``story_feed_media``,
        ``story_reshares`` or ``story_media_sticker_responses``.  The top-level
        ``image_versions2`` of the wrapper is often just the user's profile
        picture, so we dig into the nested structure to find real content."""

        # story_feed_media – reshared feed post
        for key in ("story_feed_media", "story_static_models"):
            nested_list = item.get(key)
            if isinstance(nested_list, list):
                for entry in nested_list:
                    media = entry.get("media") or entry
                    if media.get("image_versions2") or media.get("video_versions"):
                        return media
            elif isinstance(nested_list, dict):
                media = nested_list.get("media") or nested_list
                if media.get("image_versions2") or media.get("video_versions"):
                    return media

        # story_reshares
        reshares = item.get("story_reshares", {})
        if isinstance(reshares, dict):
            reshare_items = reshares.get("reshared_story") or reshares.get("media")
            if isinstance(reshare_items, dict):
                if reshare_items.get("image_versions2") or reshare_items.get("video_versions"):
                    return reshare_items

        # story_media_sticker_responses (mentioned / tagged media)
        stickers = item.get("story_media_sticker_responses") or []
        if isinstance(stickers, list):
            for sticker in stickers:
                media = sticker.get("media") or sticker
                if media.get("image_versions2") or media.get("video_versions"):
                    return media

        # clip – resharing a Reel/clip as a story
        clip = item.get("clip")
        if isinstance(clip, dict):
            media = clip.get("clip") or clip
            if media.get("image_versions2") or media.get("video_versions"):
                return media

        return None

    @staticmethod
    def _build_story_result(
        username: str, story_id: Optional[str], items: list[dict],
    ) -> Optional[ScrapedResult]:
        if not items:
            return None
        if story_id:
            specific = [
                i for i in items
                if str(i.get("pk")) == story_id
                or str(i.get("id", "")).split("_")[0] == story_id
            ]
            if specific:
                items = specific

        variants: list[ScrapedVariant] = []
        thumbnail = None

        for item in items:
            pp_name = _user_pp_filename(item)

            # If the story reshares/mentions another post, prefer its media
            inner = InstagramScraper._extract_inner_story_media(item)
            effective = inner or item
            is_direct_story = inner is None

            media_type = effective.get("media_type") or item.get("media_type")

            # Check video_versions for ANY media type – photo+audio stories
            # often have media_type=1 but still carry video_versions
            vids = effective.get("video_versions", [])
            if vids:
                usable = [v for v in vids if v.get("url") and not _is_profile_pic(v["url"], story_context=is_direct_story)]
                if usable:
                    best = max(usable, key=lambda v: v.get("width", 0) * v.get("height", 0))
                    variants.append(ScrapedVariant(
                        label=f"Story Video {len(variants) + 1}", format="mp4",
                        url=best["url"], has_video=True, has_audio=True,
                    ))

            candidates = effective.get("image_versions2", {}).get("candidates", [])
            # Filter out profile pictures and tiny images
            good_imgs = [
                c for c in candidates
                if c.get("url")
                and not _is_profile_pic(
                    c["url"], c.get("width", 0), c.get("height", 0), story_context=is_direct_story
                )
                and not (pp_name and _cdn_filename(c["url"]) == pp_name)
            ]
            if good_imgs:
                best_img = max(good_imgs, key=lambda c: c.get("width", 0) * c.get("height", 0))
                if not thumbnail:
                    thumbnail = best_img["url"]
                # Add as photo variant only if we didn't already add a video
                if not vids:
                    variants.append(ScrapedVariant(
                        label=f"Story Photo {len(variants) + 1}", format="jpg",
                        url=best_img["url"],
                    ))

        if not variants:
            return None

        return ScrapedResult(
            title=f"@{username}'s Story", author=username,
            thumbnail_url=thumbnail, content_type="story", variants=variants,
        )

    async def _playwright_extract(
        self, url: str, content_type: str, cookies: Optional[list] = None,
    ) -> Optional[ScrapedResult]:
        """Playwright with mobile viewport and cookies."""
        html = await get_page_content(
            url, use_browser=True, timeout_ms=20_000,
            viewport={"width": 412, "height": 915},
            user_agent=_MOBILE_UA, cookies=cookies,
        )
        if not html:
            return None

        # Try OG tags first
        result = parse_og_tags(html, "Instagram Content", content_type)
        if result.variants:
            return result

        # Extract CDN URLs
        variants: list[ScrapedVariant] = []
        thumbnail = None
        seen: set[str] = set()

        for raw in re.findall(
            r"(https?://(?:scontent[^.\s]*|(?:[a-z0-9-]+\.)?fbcdn|"
            r"cdninstagram|instagram)[^\s\"'\\>]+?\.mp4[^\s\"'\\>]*)",
            html, re.IGNORECASE,
        ):
            clean = unescape(raw.replace("\\u0026", "&").replace("\\/", "/"))
            if clean not in seen:
                seen.add(clean)
                variants.append(ScrapedVariant(
                    label=f"Video {len(variants) + 1}", format="mp4",
                    url=clean, has_video=True, has_audio=True,
                ))

        for raw in re.findall(
            r"(https?://(?:scontent[^.\s]*|(?:[a-z0-9-]+\.)?fbcdn|"
            r"cdninstagram|instagram)[^\s\"'\\>]+?\.(?:jpg|jpeg|png|webp)[^\s\"'\\>]*)",
            html, re.IGNORECASE,
        ):
            clean = unescape(raw.replace("\\u0026", "&").replace("\\/", "/"))
            if any(s in clean for s in (
                "profile_pic", "t51.2885-19",
            )):
                continue
            m_sq = _SQUARE_SIZE_RE.search(clean)
            if m_sq and m_sq.group(1) == m_sq.group(2):
                if int(m_sq.group(1)) <= 320:
                    continue
            if clean not in seen:
                seen.add(clean)
                if not thumbnail:
                    thumbnail = clean
                if not variants:
                    variants.append(ScrapedVariant(
                        label=f"Photo {len(variants) + 1}", format="jpg", url=clean,
                    ))

        if not variants:
            return None

        return ScrapedResult(
            title="Instagram Story" if "stor" in content_type else "Instagram Post",
            thumbnail_url=thumbnail, content_type=content_type, variants=variants,
        )

    async def _scrape_embed(self, shortcode: str) -> ScrapedResult:
        """Parse Instagram's public embed page."""
        embed_url = f"https://www.instagram.com/p/{shortcode}/embed/"
        html = await get_page_content(embed_url)
        if not html:
            return ScrapedResult(title="Instagram Post", content_type="image")

        variants: list[ScrapedVariant] = []
        thumbnail = None

        video_match = re.search(r'<video[^>]+src="([^"]+)"', html)
        if not video_match:
            video_match = re.search(r'"video_url"\s*:\s*"([^"]+)"', html)
        if video_match:
            video_url = unescape(
                video_match.group(1).replace("\\u0026", "&").replace("\\/", "/")
            )
            variants.append(ScrapedVariant(
                label="Video", format="mp4", url=video_url,
                has_video=True, has_audio=True,
            ))

        seen: set[str] = set()
        for raw in re.findall(
            r"(https://(?:scontent[^.\s]*|instagram|cdninstagram|"
            r"(?:[a-z0-9-]+\.)?fbcdn)[^\s\"'\\]+\.(?:jpg|png|webp)[^\s\"'\\]*)",
            html,
        ):
            clean = unescape(raw.replace("\\u0026", "&").replace("\\/", "/"))
            if "150x150" in clean or clean in seen:
                continue
            seen.add(clean)
            if not thumbnail:
                thumbnail = clean
            variants.append(ScrapedVariant(
                label=f"Image {len([v for v in variants if not v.has_video]) + 1}",
                format="jpg", url=clean,
            ))

        author_match = re.search(r'"author_name"\s*:\s*"([^"]*)"', html)
        caption_match = re.search(r'class="[^"]*Caption[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
        caption = re.sub(r"<[^>]+>", "", caption_match.group(1))[:120].strip() if caption_match else ""

        return ScrapedResult(
            title=caption or "Instagram Post",
            author=author_match.group(1) if author_match else None,
            thumbnail_url=thumbnail,
            content_type="video" if any(v.has_video for v in variants) else "image",
            variants=variants,
        )

    # ── URL parsers ──────────────────────────────────────────────

    @staticmethod
    def _extract_shortcode(url: str) -> Optional[str]:
        m = re.search(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)", url)
        return m.group(1) if m else None

    @staticmethod
    def _parse_story_url(url: str) -> tuple[Optional[str], Optional[str]]:
        m = re.search(r"/stories/([^/?#]+)(?:/(\d+))?", url)
        return (m.group(1), m.group(2)) if m else (None, None)

    @staticmethod
    def _shortcode_to_media_id(shortcode: str) -> Optional[int]:
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        media_id = 0
        for char in shortcode:
            idx = alphabet.find(char)
            if idx == -1:
                return None
            media_id = media_id * 64 + idx
        return media_id
