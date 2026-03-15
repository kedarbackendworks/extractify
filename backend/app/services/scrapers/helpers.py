"""
Shared scraper utilities – common variant building and OG-tag parsing.

Every platform scraper can import these instead of duplicating the logic.
"""

import re
from html import unescape
from typing import Optional, List

from app.services.scrapers.base import ScrapedResult, ScrapedVariant


# ── yt-dlp variant builder ───────────────────────────────────────


def build_ytdlp_variants(info: dict) -> List[ScrapedVariant]:
    """
    Build a variant list from a yt-dlp info dict.

    Filters out non-downloadable formats (mhtml, non-HTTP protocols).
    Falls back to the top-level ``url`` key when no per-format entries exist.
    """
    variants: list[ScrapedVariant] = []
    for fmt in info.get("formats", []):
        url = fmt.get("url")
        if not url:
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
            label = f"{height}p" if height else fmt.get("format_note", "unknown")
        elif has_audio and not has_video:
            label = f"audio-{fmt.get('ext', 'webm')}"
        elif has_video:
            label = (
                f"{height}p (video only)"
                if height
                else fmt.get("format_note", "unknown")
            )
        else:
            continue

        variants.append(
            ScrapedVariant(
                label=label,
                format=fmt.get("ext", "mp4"),
                url=url,
                quality=fmt.get("format_note"),
                file_size_bytes=fmt.get("filesize") or fmt.get("filesize_approx"),
                has_video=has_video,
                has_audio=has_audio,
            )
        )

    # Fallback: top-level ``url`` when no per-format entries exist
    if not variants and info.get("url"):
        variants.append(
            ScrapedVariant(
                label="source",
                format=info.get("ext", "mp4"),
                url=info["url"],
                has_video=True,
                has_audio=True,
            )
        )

    return variants


# ── OG-tag helpers ───────────────────────────────────────────────


def find_og_tag(html: str, prop: str) -> Optional[str]:
    """
    Find an Open Graph meta tag value regardless of attribute order.

    Checks ``property="og:…" content="…"`` and the reversed ordering,
    as well as ``name="og:…"`` variants.
    """
    patterns = [
        rf'<meta[^>]*property="{prop}"[^>]*content="([^"]*)"[^>]*>',
        rf'<meta[^>]*content="([^"]*)"[^>]*property="{prop}"[^>]*>',
        rf'<meta[^>]*name="{prop}"[^>]*content="([^"]*)"[^>]*>',
        rf'<meta[^>]*content="([^"]*)"[^>]*name="{prop}"[^>]*>',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def parse_og_tags(
    html: str,
    default_title: str = "Content",
    content_type: str = "other",
) -> ScrapedResult:
    """
    Build a ``ScrapedResult`` from Open Graph meta tags found in *html*.

    Handles both ``property`` / ``content`` orderings and un-escapes
    HTML entities in the extracted values.
    """
    variants: list[ScrapedVariant] = []
    thumbnail = None

    # Try multiple OG video tag variants — sites use different keys
    og_video = (
        find_og_tag(html, "og:video:secure_url")
        or find_og_tag(html, "og:video:url")
        or find_og_tag(html, "og:video")
    )
    og_image = find_og_tag(html, "og:image")
    og_title = find_og_tag(html, "og:title")
    og_desc = find_og_tag(html, "og:description")

    if og_video:
        video_url = unescape(og_video)
        variants.append(
            ScrapedVariant(
                label="Video",
                format="mp4",
                url=video_url,
                has_video=True,
                has_audio=True,
            )
        )
        content_type = "video"

    if og_image:
        image_url = unescape(og_image)
        thumbnail = image_url
        variants.append(
            ScrapedVariant(label="Image", format="jpg", url=image_url)
        )

    return ScrapedResult(
        title=unescape(og_title) if og_title else default_title,
        description=unescape(og_desc) if og_desc else None,
        thumbnail_url=thumbnail,
        content_type=content_type,
        variants=variants,
    )
