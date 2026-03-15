"""
yt-dlp async helper – runs yt-dlp extraction in a thread pool
so it doesn't block the async event loop.
"""

import os
import asyncio
from functools import partial
from typing import Any, Dict

import yt_dlp
import structlog
from app.core.config import settings

logger = structlog.get_logger()

# ── Base directory (backend/) for resolving relative paths ────────
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Default yt-dlp options
_YDL_OPTS: dict = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,              # we only want metadata + URLs
    "noplaylist": True,
    "socket_timeout": 10,               # 10s per socket op
    "extractor_retries": 2,             # retry on transient errors
    "ignore_no_formats_error": True,    # don't error on format selection
}

# ── Optional proxy ───────────────────────────────────────────────
# Set YTDLP_PROXY in .env to route yt-dlp through a proxy.
_proxy = os.getenv("YTDLP_PROXY", "").strip()
if _proxy:
    _YDL_OPTS["proxy"] = _proxy
    logger.info("ytdlp_proxy_configured", proxy=_proxy[:30] + "…")

# ── Cookie support (general, non-YouTube) ────────────────────────
# Set YTDLP_COOKIES_FILE in .env to authenticate with other platforms.
# YouTube does NOT use cookies — PO Tokens handle auth instead.
if settings.YTDLP_COOKIES_FILE:
    _cookie_path = settings.YTDLP_COOKIES_FILE
    if os.path.isfile(_cookie_path):
        _YDL_OPTS["cookiefile"] = _cookie_path
    else:
        _abs = os.path.join(_BACKEND_DIR, _cookie_path)
        if os.path.isfile(_abs):
            _YDL_OPTS["cookiefile"] = _abs

logger.info("ytdlp_helper_ready", has_pot_provider=True, has_proxy=bool(_proxy))

import re
_YT_RE = re.compile(r"(youtube\.com|youtu\.be)", re.IGNORECASE)

class _YtdlpDebugLogger:
    """Captures yt-dlp debug output for structlog."""
    def __init__(self): self.lines = []
    def debug(self, msg):
        if isinstance(msg, str):
            self.lines.append(msg)
    def warning(self, msg):
        if isinstance(msg, str):
            self.lines.append(f"WARN: {msg}")
    def error(self, msg):
        if isinstance(msg, str):
            self.lines.append(f"ERR: {msg}")


def _extract_sync(url: str, extra_opts: dict | None = None) -> Dict[str, Any]:
    """Synchronous extraction (runs in thread pool)."""
    opts = {**_YDL_OPTS, **(extra_opts or {})}
    is_youtube = _YT_RE.search(url)
    debug_logger = None

    # For YouTube: enable verbose mode to see POT/plugin activity
    if is_youtube:
        debug_logger = _YtdlpDebugLogger()
        opts["quiet"] = False
        opts["verbose"] = True
        opts["no_warnings"] = False
        opts["logger"] = debug_logger
        opts["socket_timeout"] = 30  # POT generation needs more time

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        result = ydl.sanitize_info(info)  # type: ignore[arg-type]

        if is_youtube and debug_logger:
            fmts = result.get("formats", [])
            # Log key debug lines about POT/plugin/playability
            pot_lines = [l for l in debug_logger.lines
                         if any(k in l.lower() for k in
                                ["pot", "bgutil", "plugin", "provider",
                                 "playab", "token", "sign in", "bot"])]
            logger.info(
                "ytdlp_youtube_debug",
                total_formats=len(fmts),
                title=str(result.get("title", ""))[:60],
                pot_plugin_lines=pot_lines[:15],
            )

        return result


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

