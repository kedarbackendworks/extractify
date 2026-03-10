"""
Snapchat scraper – Spotlight, public Stories & Highlights.

Spotlight  → yt-dlp  (direct video links)
Stories    → __NEXT_DATA__ JSON embedded in the profile page HTML
Highlights → same __NEXT_DATA__ source (curatedHighlights)
"""

import json
import re
from typing import List, Optional
from urllib.parse import urlencode

import httpx

from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.utils.ytdlp_helper import extract_with_ytdlp


# Maps snapMediaType int → human label
_MEDIA_TYPE = {0: "image", 1: "video"}

_PROFILE_UA = "facebookexternalhit/1.1"


class SnapchatScraper(BaseScraper):
    platform = "snapchat"

    _DOMAIN_RE = re.compile(r"snapchat\.com")

    # Regex to extract username from various Snapchat URL formats
    _USERNAME_RE = re.compile(
        r"snapchat\.com/"
        r"(?:@|add/|stories/|story/|s/|u/)"
        r"([A-Za-z0-9._-]+)",
    )
    # Bare username: snapchat.com/username (no prefix)
    _BARE_USER_RE = re.compile(
        r"snapchat\.com/([A-Za-z0-9._-]+)/?(?:\?.*)?$",
    )

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    @classmethod
    def _normalize_profile_url(cls, url: str) -> str:
        """Normalize any Snapchat profile URL to https://www.snapchat.com/@username."""
        m = cls._USERNAME_RE.search(url)
        if m:
            return f"https://www.snapchat.com/@{m.group(1)}"
        m = cls._BARE_USER_RE.search(url)
        if m:
            username = m.group(1)
            # Skip known non-username paths
            if username not in ("download", "p", "discover", "lens", "unlock"):
                return f"https://www.snapchat.com/@{username}"
        return url

    # ── public entry point ──────────────────────────────────────────
    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        # Spotlight videos → yt-dlp (fast & reliable)
        if "/spotlight/" in url:
            return await self._scrape_spotlight(url)

        # Single highlight URL → fetch that specific highlight only
        if "/highlight/" in url:
            return await self._scrape_single_highlight(url)

        # Normalize & route to profile scraper
        normalized = self._normalize_profile_url(url)
        if normalized != url or any(p in url for p in ("/@", "/add/", "/stories/", "/story/", "/s/", "/u/")):
            return await self._scrape_profile(normalized, content_tab)

        # Fallback: try spotlight first, then profile
        try:
            return await self._scrape_spotlight(url)
        except Exception:
            return await self._scrape_profile(normalized, content_tab)

    # ── Spotlight via yt-dlp ────────────────────────────────────────
    async def _scrape_spotlight(self, url: str) -> ScrapedResult:
        info = await extract_with_ytdlp(url)
        variants: List[ScrapedVariant] = []
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
                file_size_bytes=fmt.get("filesize") or fmt.get("filesize_approx"),
                has_video=has_video,
                has_audio=has_audio,
            ))
        return ScrapedResult(
            title=info.get("title", "Snapchat Spotlight"),
            author=info.get("uploader"),
            thumbnail_url=info.get("thumbnail"),
            duration_seconds=info.get("duration"),
            content_type="short",
            variants=variants,
        )

    # ── Single highlight by URL ──────────────────────────────────────
    async def _scrape_single_highlight(self, url: str) -> ScrapedResult:
        """Scrape a single highlight from its direct URL."""
        props = await self._fetch_page_props(url)

        highlight = props.get("highlight")
        if not highlight or not highlight.get("snapList"):
            raise ValueError("Could not load this highlight — it may have been removed.")

        # Author info from publicUserProfile (different key than profile pages)
        pub = props.get("publicUserProfile") or {}
        author = pub.get("title") or pub.get("username") or ""
        avatar = pub.get("profilePictureUrl") or pub.get("snapcodeImageUrl")

        title_obj = highlight.get("storyTitle") or {}
        hl_title = title_obj.get("value", "") if isinstance(title_obj, dict) else str(title_obj)

        display_title = hl_title or "Highlight"
        if author:
            display_title = f"{author} — {display_title}"

        snaps = highlight.get("snapList", [])
        variants = self._snaps_to_variants(snaps, prefix=hl_title or "Highlight")
        merged = self._make_merged_variant(snaps, display_title)
        if merged:
            variants.insert(0, merged)
        thumb_raw = highlight.get("thumbnailUrl")
        if isinstance(thumb_raw, dict):
            thumb_raw = thumb_raw.get("value")
        thumb = thumb_raw or self._first_preview(snaps)

        return ScrapedResult(
            title=display_title,
            author=author or None,
            thumbnail_url=thumb or avatar,
            content_type="story",
            variants=variants,
        )

    # ── Profile / Story / Highlights via __NEXT_DATA__ ──────────────
    async def _scrape_profile(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        props = await self._fetch_page_props(url)

        # Determine author info
        profile = props.get("userProfile") or {}
        pub = profile.get("publicProfileInfo") or profile.get("userInfo") or {}
        author = pub.get("title") or pub.get("displayName") or pub.get("username") or ""
        username = pub.get("username", "")
        avatar = pub.get("profilePictureUrl") or pub.get("snapcodeImageUrl")

        # Collect available content sections
        story = props.get("story")                          # active story (24h)
        highlights = props.get("curatedHighlights") or []   # saved highlights
        spotlight_items = props.get("spotlightHighlights") or []

        # Route strictly by content_tab when provided
        tab = (content_tab or "").lower()
        if tab == "stories":
            if story and story.get("snapList"):
                return self._build_story_result(story, author, avatar)
            raise ValueError(
                f"No active stories found for @{username or 'this user'}. "
                "Stories expire after 24 hours — try again when a new story is posted."
            )
        if tab == "highlights":
            if highlights:
                return self._build_highlights_result(highlights, author, avatar)
            raise ValueError(
                f"No public highlights found for @{username or 'this user'}."
            )
        if tab == "spotlight":
            if spotlight_items:
                return self._build_spotlight_profile_result(spotlight_items, author, avatar)
            raise ValueError(
                f"No spotlight content found for @{username or 'this user'}."
            )

        # No tab specified — return first available section
        if story and story.get("snapList"):
            return self._build_story_result(story, author, avatar)
        if highlights:
            return self._build_highlights_result(highlights, author, avatar)
        if spotlight_items:
            return self._build_spotlight_profile_result(spotlight_items, author, avatar)

        raise ValueError(
            f"No public stories, highlights or spotlight content found for @{username or 'this user'}. "
            "The user may not have any active public stories right now."
        )

    # ── Fetch & parse __NEXT_DATA__ ─────────────────────────────────
    async def _fetch_page_props(self, url: str) -> dict:
        """Fetch Snapchat profile page and return pageProps from __NEXT_DATA__."""
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=15,
            headers={"User-Agent": _PROFILE_UA},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            resp.text,
            re.DOTALL,
        )
        if not match:
            raise ValueError("Could not parse Snapchat page data")

        data = json.loads(match.group(1))
        return data.get("props", {}).get("pageProps", {})

    # ── Build results from story snapList ───────────────────────────
    def _build_story_result(
        self, story: dict, author: str, avatar: Optional[str]
    ) -> ScrapedResult:
        """Build ScrapedResult from an active story."""
        snaps = story.get("snapList", [])
        variants = self._snaps_to_variants(snaps, prefix="Story")
        merged = self._make_merged_variant(snaps, f"{author}'s Story" if author else "Story")
        if merged:
            variants.insert(0, merged)
        thumb = self._first_preview(snaps)
        return ScrapedResult(
            title=f"{author}'s Story" if author else "Snapchat Story",
            author=author or None,
            thumbnail_url=thumb or avatar,
            content_type="story",
            variants=variants,
        )

    def _build_highlights_result(
        self, highlights: list, author: str, avatar: Optional[str]
    ) -> ScrapedResult:
        """Build ScrapedResult merging all highlight albums."""
        variants: List[ScrapedVariant] = []
        for hl in highlights:
            title_obj = hl.get("title") or {}
            hl_title = title_obj.get("value", "") if isinstance(title_obj, dict) else str(title_obj)
            snaps = hl.get("snapList", [])
            # Add merged variant for this highlight album first
            merged = self._make_merged_variant(snaps, hl_title or "Highlight")
            if merged:
                variants.append(merged)
            variants.extend(self._snaps_to_variants(snaps, prefix=hl_title or "Highlight"))
        thumb = self._first_preview(highlights[0].get("snapList", [])) if highlights else None
        return ScrapedResult(
            title=f"{author}'s Highlights" if author else "Snapchat Highlights",
            author=author or None,
            thumbnail_url=thumb or avatar,
            content_type="story",
            variants=variants,
        )

    def _build_spotlight_profile_result(
        self, items: list, author: str, avatar: Optional[str]
    ) -> ScrapedResult:
        """Build ScrapedResult from spotlight highlights on a profile."""
        variants: List[ScrapedVariant] = []
        for item in items:
            snaps = item.get("snapList", [])
            variants.extend(self._snaps_to_variants(snaps, prefix="Spotlight"))
        thumb = self._first_preview(items[0].get("snapList", [])) if items else None
        return ScrapedResult(
            title=f"{author}'s Spotlight" if author else "Snapchat Spotlight",
            author=author or None,
            thumbnail_url=thumb or avatar,
            content_type="short",
            variants=variants,
        )

    # ── helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _snaps_to_variants(snaps: list, prefix: str = "") -> List[ScrapedVariant]:
        """Convert a list of snap dicts into ScrapedVariant objects."""
        out: List[ScrapedVariant] = []
        for i, snap in enumerate(snaps):
            urls = snap.get("snapUrls") or {}
            media_url = urls.get("mediaUrl")
            if not media_url:
                continue
            media_type = snap.get("snapMediaType", 0)
            is_video = media_type == 1
            idx = i + 1
            if is_video:
                label = f"{prefix} Video {idx}" if prefix else f"Video {idx}"
                fmt = "mp4"
            else:
                label = f"{prefix} Image {idx}" if prefix else f"Image {idx}"
                fmt = "jpg"
            out.append(ScrapedVariant(
                label=label.strip(),
                format=fmt,
                url=media_url,
                has_video=is_video,
                has_audio=is_video,
            ))
        return out

    @staticmethod
    def _make_merged_variant(snaps: list, title: str) -> Optional[ScrapedVariant]:
        """Create a single merged-video variant from multiple snaps.

        Returns a variant whose URL points to /api/download/merge with
        pipe-separated snap URLs so the backend concatenates them with ffmpeg.
        """
        media_urls: List[str] = []
        for snap in snaps:
            snap_urls = snap.get("snapUrls") or {}
            media_url = snap_urls.get("mediaUrl")
            if media_url:
                media_urls.append(media_url)
        if len(media_urls) < 2:
            return None
        pipe_urls = "|".join(media_urls)
        safe_title = re.sub(r'[^\w \-]', '', title.replace('\n', ' ').replace('\r', ''))[:80].strip() or "download"
        merge_url = f"/api/download/merge?{urlencode({'urls': pipe_urls, 'filename': safe_title})}"
        return ScrapedVariant(
            label=f"{title} — Full Video (merged)",
            format="mp4",
            url=merge_url,
            has_video=True,
            has_audio=True,
        )

    @staticmethod
    def _first_preview(snaps: list) -> Optional[str]:
        """Return the first preview image URL from a snapList, if any."""
        for snap in snaps:
            urls = snap.get("snapUrls") or {}
            preview = urls.get("mediaPreviewUrl")
            if isinstance(preview, dict):
                preview = preview.get("value")
            if preview:
                return preview
        return None
