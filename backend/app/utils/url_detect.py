"""
URL detection utility – maps a URL to its platform slug + category.
Mirrors the frontend platformMap in page.tsx.
"""

from typing import Tuple, Optional

_PLATFORM_MAP: dict[str, Tuple[str, str]] = {
    # domain → (platform_slug, category)
    # ── Social ──────────────────────────────────
    "instagram.com": ("instagram", "social"),
    "instagr.am": ("instagram", "social"),
    "youtube.com": ("youtube", "social"),
    "youtu.be": ("youtube", "social"),
    "tiktok.com": ("tiktok", "social"),
    "twitter.com": ("twitter", "social"),
    "x.com": ("twitter", "social"),
    "facebook.com": ("facebook", "social"),
    "fb.com": ("facebook", "social"),
    "fb.watch": ("facebook", "social"),
    "snapchat.com": ("snapchat", "social"),
    "story.snapchat.com": ("snapchat", "social"),
    "linkedin.com": ("linkedin", "social"),
    "pinterest.com": ("pinterest", "social"),
    "pin.it": ("pinterest", "social"),
    "reddit.com": ("reddit", "social"),
    "tumblr.com": ("tumblr", "social"),
    "twitch.tv": ("twitch", "social"),
    "vimeo.com": ("vimeo", "social"),
    "vk.com": ("vk", "social"),
    "soundcloud.com": ("soundcloud", "social"),
    "t.me": ("telegram", "social"),
    "telegram.org": ("telegram", "social"),
    "threads.net": ("threads", "social"),
    "threads.com": ("threads", "social"),
    # ── Document ────────────────────────────────
    "scribd.com": ("scribd", "document"),
    "slideshare.net": ("slideshare", "document"),
    "issuu.com": ("issuu", "document"),
    "calameo.com": ("calameo", "document"),
    "yumpu.com": ("yumpu", "document"),
    "slideserve.com": ("slideserve", "document"),
}


def detect_platform(url: str) -> Tuple[Optional[str], str]:
    """
    Returns (platform_slug, category) or (None, "unknown").
    """
    for domain, (slug, cat) in _PLATFORM_MAP.items():
        if domain in url:
            return slug, cat
    return None, "unknown"
