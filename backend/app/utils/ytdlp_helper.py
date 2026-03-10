"""
yt-dlp async helper – runs yt-dlp extraction in a thread pool
so it doesn't block the async event loop.
"""

import os
import asyncio
from functools import partial
from typing import Any, Dict

import yt_dlp
from app.core.config import settings

# Default yt-dlp options
_YDL_OPTS: dict = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,              # we only want metadata + URLs
    "noplaylist": True,
    "socket_timeout": 20,
    "extractor_retries": 2,
    "ignore_no_formats_error": True,    # don't error on format selection
}

# ── Cookie support ────────────────────────────────────────────────
# Set YTDLP_COOKIES_FILE in .env to a Netscape-format cookies.txt
# path to authenticate with platforms that need login.
if settings.YTDLP_COOKIES_FILE:
    _cookie_path = settings.YTDLP_COOKIES_FILE
    if os.path.isfile(_cookie_path):
        _YDL_OPTS["cookiefile"] = _cookie_path

# Instagram-specific cookies.txt (used by InstagramScraper directly,
# but also serve as a fallback if YTDLP_COOKIES_FILE is not set)
_IG_COOKIE_FILE: str | None = None
if settings.INSTAGRAM_COOKIES_FILE:
    _ig_path = settings.INSTAGRAM_COOKIES_FILE
    if os.path.isfile(_ig_path):
        _IG_COOKIE_FILE = _ig_path
    else:
        # Check relative to backend dir
        _abs_ig = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), _ig_path)
        if os.path.isfile(_abs_ig):
            _IG_COOKIE_FILE = _abs_ig


def _extract_sync(url: str, extra_opts: dict | None = None) -> Dict[str, Any]:
    """Synchronous extraction (runs in thread pool)."""
    opts = {**_YDL_OPTS, **(extra_opts or {})}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return ydl.sanitize_info(info)  # type: ignore[arg-type]


async def extract_with_ytdlp(
    url: str,
    extra_opts: dict | None = None,
) -> Dict[str, Any]:
    """
    Async wrapper: extracts metadata + format list from a URL.
    Returns the yt-dlp info dict.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        partial(_extract_sync, url, extra_opts),
    )
