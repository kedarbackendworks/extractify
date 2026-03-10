"""
Reddit scraper – uses Reddit's public JSON API (no authentication needed).

Handles:
  - Image posts      (i.redd.it)
  - Gallery posts    (multiple images)
  - Video posts      (v.redd.it – separate audio/video streams)
  - GIF posts
  - Cross-posts
"""

import re
from html import unescape
from typing import Optional
from urllib.parse import urlparse, urlunparse

import httpx
from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.services.scrapers.helpers import build_ytdlp_variants, parse_og_tags
from app.utils.ytdlp_helper import extract_with_ytdlp
from app.utils.browser import get_page_content


class RedditScraper(BaseScraper):
    platform = "reddit"

    _DOMAIN_RE = re.compile(r"(reddit\.com|redd\.it)")

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        # Resolve short URLs and normalise
        resolved = await self._resolve_short_url(url)
        clean_url = self._normalize_url(resolved)

        # ── Strategy 1: Reddit JSON API (most reliable) ──────────
        try:
            result = await self._scrape_json_api(clean_url)
            if result and result.variants:
                return result
        except Exception:
            pass

        # ── Strategy 2: yt-dlp (video posts) ─────────────────────
        try:
            info = await extract_with_ytdlp(clean_url)
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

        # ── Strategy 3: Playwright OG tags ───────────────────────
        html = await get_page_content(clean_url)
        if html:
            result = parse_og_tags(html, "Reddit Post", "other")
            if result.variants:
                return result

        raise ValueError("Could not extract this Reddit post.")

    # ── Private helpers ──────────────────────────────────────────

    async def _resolve_short_url(self, url: str) -> str:
        """Resolve redd.it short URLs to full reddit.com URLs."""
        if "redd.it" in url and "reddit.com" not in url:
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True, timeout=10
                ) as client:
                    resp = await client.head(url)
                    return str(resp.url)
            except Exception:
                pass
        return url

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Convert old/np Reddit subdomains to www."""
        url = url.replace("old.reddit.com", "www.reddit.com")
        url = url.replace("np.reddit.com", "www.reddit.com")
        return url

    async def _scrape_json_api(self, url: str) -> Optional[ScrapedResult]:
        """Fetch post data from Reddit's public JSON API."""
        parsed = urlparse(url)
        json_path = parsed.path.rstrip("/") + ".json"
        json_url = urlunparse(
            (parsed.scheme, parsed.netloc, json_path, "", "", "")
        )

        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Extractify/1.0)"},
        ) as client:
            resp = await client.get(json_url)
            resp.raise_for_status()
            data = resp.json()

        # Reddit returns  [post_listing, comments_listing]
        if not isinstance(data, list) or len(data) < 1:
            return None

        children = data[0].get("data", {}).get("children", [])
        if not children:
            return None

        post = children[0].get("data", {})
        if not post:
            return None

        title = post.get("title", "Reddit Post")
        author = post.get("author")
        subreddit = post.get("subreddit_name_prefixed", "")
        variants: list[ScrapedVariant] = []
        thumbnail: Optional[str] = None
        content_type = "other"

        # ── Video posts ──────────────────────────────────────────
        if post.get("is_video") and post.get("media"):
            rv = post["media"].get("reddit_video", {})
            fallback_url = rv.get("fallback_url")
            if fallback_url:
                clean_video = fallback_url.split("?")[0]
                height = rv.get("height")
                duration = rv.get("duration")
                variants.append(
                    ScrapedVariant(
                        label=f"{height}p" if height else "Video",
                        format="mp4",
                        url=fallback_url,
                        has_video=True,
                        has_audio=True,
                    )
                )
                # Audio is served separately in Reddit DASH
                audio_url = re.sub(r"DASH_\d+", "DASH_AUDIO_128", clean_video)
                variants.append(
                    ScrapedVariant(
                        label="Audio only",
                        format="mp4",
                        url=audio_url,
                        has_video=False,
                        has_audio=True,
                    )
                )
                content_type = "video"
                thumbnail = post.get("thumbnail")
                return ScrapedResult(
                    title=title,
                    description=f"Posted by u/{author} in {subreddit}",
                    author=author,
                    thumbnail_url=(
                        thumbnail
                        if thumbnail and thumbnail.startswith("http")
                        else None
                    ),
                    duration_seconds=duration,
                    content_type=content_type,
                    variants=variants,
                )

        # ── Gallery posts ────────────────────────────────────────
        if post.get("is_gallery") and post.get("media_metadata"):
            metadata = post["media_metadata"]
            gallery_items = post.get("gallery_data", {}).get("items", [])
            for i, item in enumerate(gallery_items):
                media_id = item.get("media_id")
                if not media_id or media_id not in metadata:
                    continue
                media = metadata[media_id]
                source = media.get("s", {})
                img_url = source.get("u") or source.get("gif")
                if img_url:
                    img_url = unescape(img_url)
                    if not thumbnail:
                        thumbnail = img_url
                    ext = "gif" if source.get("gif") else "jpg"
                    variants.append(
                        ScrapedVariant(
                            label=f"Image {i + 1}",
                            format=ext,
                            url=img_url,
                        )
                    )
            if variants:
                content_type = "image"
                return ScrapedResult(
                    title=title,
                    description=f"Posted by u/{author} in {subreddit} ({len(variants)} images)",
                    author=author,
                    thumbnail_url=thumbnail,
                    content_type=content_type,
                    variants=variants,
                )

        # ── Single-image posts ───────────────────────────────────
        post_url = post.get("url", "")
        if re.search(
            r"\.(jpg|jpeg|png|gif|webp)(\?|$)", post_url, re.IGNORECASE
        ):
            thumbnail = post_url
            fmt = "gif" if ".gif" in post_url.lower() else "jpg"
            variants.append(
                ScrapedVariant(label="Original", format=fmt, url=post_url)
            )
            content_type = "image"

        # ── External GIF / rich video embed ──────────────────────
        elif "gif" in post_url.lower() or post.get("post_hint") == "rich:video":
            preview = post.get("preview", {})
            reddit_preview = preview.get("reddit_video_preview", {})
            if reddit_preview.get("fallback_url"):
                variants.append(
                    ScrapedVariant(
                        label="GIF Video",
                        format="mp4",
                        url=reddit_preview["fallback_url"],
                        has_video=True,
                        has_audio=False,
                    )
                )
                content_type = "video"
            elif post_url:
                variants.append(
                    ScrapedVariant(label="Link", format="gif", url=post_url)
                )
                content_type = "image"

        # ── Preview images as last resort ────────────────────────
        if not variants:
            preview = post.get("preview", {})
            images = preview.get("images", [])
            if images:
                source = images[0].get("source", {})
                img_url = source.get("url")
                if img_url:
                    img_url = unescape(img_url)
                    thumbnail = img_url
                    variants.append(
                        ScrapedVariant(label="Preview", format="jpg", url=img_url)
                    )
                    content_type = "image"

        if not variants:
            return None

        return ScrapedResult(
            title=title,
            description=f"Posted by u/{author} in {subreddit}",
            author=author,
            thumbnail_url=(
                thumbnail if thumbnail and thumbnail.startswith("http") else None
            ),
            content_type=content_type,
            variants=variants,
        )
