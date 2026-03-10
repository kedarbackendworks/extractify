"""
Playwright-based browser helper for JS-heavy pages.
Falls back to httpx for simple HTML fetches.

On Windows (Python from Microsoft Store) Playwright's async subprocess
spawning can raise ``NotImplementedError``.  We detect that at launch time
and automatically fall back to running the **sync** Playwright API inside a
thread-pool executor so the rest of the async code is unaffected.
"""

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger()

# ── Lazy-loaded singletons ──────────────────────────────────────
_browser = None
_pw = None
_use_sync_fallback: bool | None = None   # None = not tried yet
_thread_pool = ThreadPoolExecutor(max_workers=2)


# ── Async Playwright launcher ──────────────────────────────────
async def _get_browser():
    """Launch (or reuse) a headless Chromium instance (async API)."""
    global _browser, _pw, _use_sync_fallback

    if _browser is not None:
        return _browser

    try:
        from playwright.async_api import async_playwright
        _pw = await async_playwright().start()
        _browser = await _pw.chromium.launch(headless=True)
        _use_sync_fallback = False
        return _browser
    except NotImplementedError:
        # Windows ProactorEventLoop + MS-Store Python ≥ 3.13
        _use_sync_fallback = True
        logger.warning(
            "playwright_async_not_supported",
            hint="Falling back to sync Playwright in thread pool",
        )
        return None


# ── Sync Playwright helpers (thread-safe) ───────────────────────
_sync_browser = None
_sync_pw = None
_sync_broken = False           # True once we know sync PW also fails


def _get_sync_browser():
    """Launch (or reuse) a sync Playwright Chromium instance."""
    global _sync_browser, _sync_pw, _sync_broken
    if _sync_broken:
        raise RuntimeError(
            "Playwright is unavailable on this Python installation "
            "(Microsoft Store Python does not support subprocess spawning). "
            "Install Python from https://www.python.org to enable browser rendering."
        )
    if _sync_browser is None:
        try:
            # On Windows, uvicorn sets SelectorEventLoopPolicy which does
            # NOT support subprocess spawning.  Restore ProactorEventLoop.
            if sys.platform == "win32":
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            from playwright.sync_api import sync_playwright
            _sync_pw = sync_playwright().start()
            _sync_browser = _sync_pw.chromium.launch(headless=True)
        except (NotImplementedError, Exception) as e:
            _sync_broken = True
            logger.error(
                "sync_playwright_also_broken",
                error=f"{type(e).__name__}: {e}",
                hint="Playwright cannot run on MS Store Python 3.13+",
            )
            raise RuntimeError(
                f"Playwright unavailable ({type(e).__name__}). "
                "Install Python from python.org to fix."
            ) from e
    return _sync_browser


def _sync_fetch(
    url: str,
    wait_for: Optional[str],
    timeout_ms: int,
    viewport: Optional[dict] = None,
    user_agent: Optional[str] = None,
    cookies: Optional[list] = None,
) -> str:
    """Run a full Playwright page load synchronously (called from thread)."""
    browser = _get_sync_browser()
    ctx_kwargs: dict = {}
    if viewport:
        ctx_kwargs["viewport"] = viewport
    if user_agent:
        ctx_kwargs["user_agent"] = user_agent

    # Always create a context so we can inject cookies
    context = browser.new_context(**ctx_kwargs)
    if cookies:
        context.add_cookies(cookies)
    page = context.new_page()

    try:
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        if wait_for:
            page.wait_for_selector(wait_for, timeout=timeout_ms)
        return page.content()
    finally:
        page.close()
        context.close()


# ── Public API ──────────────────────────────────────────────────

async def get_page_content(
    url: str,
    wait_for: Optional[str] = None,
    timeout_ms: int = 15_000,
    use_browser: bool = False,
    viewport: Optional[dict] = None,
    user_agent: Optional[str] = None,
    cookies: Optional[list] = None,
) -> str:
    """
    Fetch page content.
    - First tries a lightweight httpx GET (unless ``use_browser=True``).
    - Falls back to Playwright (async or sync-in-thread on Windows).

    Extra kwargs ``viewport``, ``user_agent``, and ``cookies`` are
    forwarded to Playwright when a browser context is created.
    ``cookies`` should be a list of dicts with keys: name, value, domain, path.
    """
    if not use_browser:
        try:
            async with httpx.AsyncClient(
                timeout=15,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        user_agent
                        or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    ),
                },
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
                if len(html) > 2000:
                    return html
        except Exception as e:
            logger.debug("httpx_fetch_failed", url=url, error=str(e))

    # Determine which Playwright path to use
    global _use_sync_fallback
    if _use_sync_fallback is None:
        # First call — try async, will set the flag
        await _get_browser()

    if _use_sync_fallback:
        # ── Sync fallback (Windows) ──────────────────────────────
        try:
            loop = asyncio.get_running_loop()
            content = await loop.run_in_executor(
                _thread_pool,
                _sync_fetch,
                url,
                wait_for,
                timeout_ms,
                viewport,
                user_agent,
                cookies,
            )
            return content
        except Exception as e:
            logger.error("sync_browser_fetch_failed", url=url, error=str(e))
            return ""

    # ── Async path (Linux / Docker / normal Python) ──────────────
    try:
        browser = await _get_browser()
        if browser is None:
            return ""

        ctx_kwargs: dict = {}
        if viewport:
            ctx_kwargs["viewport"] = viewport
        if user_agent:
            ctx_kwargs["user_agent"] = user_agent

        # Always create a context so we can inject cookies
        context = await browser.new_context(**ctx_kwargs)
        if cookies:
            await context.add_cookies(cookies)
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            if wait_for:
                await page.wait_for_selector(wait_for, timeout=timeout_ms)
            content = await page.content()
            return content
        finally:
            await page.close()
            await context.close()
    except Exception as e:
        logger.error("browser_fetch_failed", url=url, error=str(e))
        return ""


async def close_browser():
    """Graceful shutdown."""
    global _browser, _pw, _sync_browser, _sync_pw
    if _browser:
        await _browser.close()
        _browser = None
    if _pw:
        await _pw.stop()
        _pw = None
    if _sync_browser:
        _sync_browser.close()
        _sync_browser = None
    if _sync_pw:
        _sync_pw.stop()
        _sync_pw = None
