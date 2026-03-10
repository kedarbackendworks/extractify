"""
Yumpu scraper – extracts publications/magazines as PDFs.

Strategy (free documents):
  1. Extract document ID from the URL (or from the page HTML if non-standard URL)
  2. Call Yumpu's JSON API ``/xx/document/json/{doc_id}`` for metadata:
     → title, page count, image base_path, image dimensions, image title
  3. Build high-quality image URLs for every page:
     ``{base_path}{page_nr}/{big_dimension}/{page_nr}-{url_title}.jpg``
  4. Download all page images concurrently via httpx
  5. Assemble into a single PDF via ``img2pdf``
  6. Serve through ``/api/files/{name}``

Strategy (Yumpu News / subscription magazines):
  1. Load the reader page via Playwright (``/news/xx/issue/ID/read``)
  2. Wait for the Eagle flipbook player to initialise
  3. Extract ``JData.dataJson.details`` from the player's JS context.
     This contains CloudFront-signed URLs for every page at large resolution.
  4. Download all page images concurrently via httpx
  5. Assemble into a single PDF via ``img2pdf``

Supported URL patterns (free documents):
  - https://www.yumpu.com/xx/document/read/DOCUMENT_ID/name
  - https://www.yumpu.com/xx/document/view/DOCUMENT_ID/name
  - https://www.yumpu.com/xx/document/fullscreen/DOCUMENT_ID/name
  - https://www.yumpu.com/xx/embed/view/HASH
  - Any yumpu.com URL (scraper resolves doc ID from page source)

Supported URL patterns (Yumpu News magazines):
  - https://www.yumpu.com/xx/magazines/ID-slug
  - https://www.yumpu.com/news/xx/issue/ID-slug
  - https://www.yumpu.com/news/xx/issue/ID-slug/read
  - https://www.yumpu.com/news/xx/magazine/ID-slug
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import tempfile
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import httpx
import img2pdf
import structlog
from PIL import Image

from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.services.scrapers.helpers import find_og_tag

logger = structlog.get_logger()

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Re-use the same temp directory as other document scrapers
PDF_DIR = Path(tempfile.gettempdir()) / "extractify_pdfs"
PDF_DIR.mkdir(parents=True, exist_ok=True)

_MAX_PAGES = 500

# Multiple regexes to extract document ID from various URL formats
_DOC_ID_PATTERNS = [
    # Standard: /xx/document/read|view|fullscreen/12345/title
    re.compile(r"yumpu\.com/\w+/document/(?:read|view|fullscreen)/(\d+)", re.I),
    # Embed: /xx/embed/view/HASH  – no numeric ID (handled separately)
    # Any numeric ID after yumpu.com path segments
    re.compile(r"yumpu\.com/[^?#]*?/(\d{5,})", re.I),
]

# Yumpu JSON API endpoint (the /json/ endpoint returns all pages, /json2/ may truncate)
_JSON_API = "https://www.yumpu.com/{lang}/document/json/{doc_id}"

# Yumpu News (subscription-only) URL patterns
_YUMPU_NEWS_RE = re.compile(
    r"yumpu\.com/(?:"
    r"(?:\w{2}/)?magazines/"        # /en/magazines/901-classic-rock
    r"|news/(?:\w{2}/)?(?:issue|magazine)/"  # /news/en/issue/184434-...
    r")",
    re.I,
)
# Extract issue ID from Yumpu News issue URL
_NEWS_ISSUE_RE = re.compile(r"/issue/(\d+)", re.I)

# Reader URL suffix (already a reader page)
_NEWS_READER_RE = re.compile(r"/issue/\d+[^/]*/read", re.I)

# Thread pool for running sync Playwright on Windows
_PW_POOL = ThreadPoolExecutor(max_workers=2)

# JS expression to extract Eagle player page data from the reader page.
# Returns {base_path, large_dir, signed_images, title, pages, thumbnail} or null.
_EAGLE_EXTRACT_JS = """() => {
    const api = window.yumpu_eagle_api_0;
    if (!api || !api.mainRef) return null;
    const jdata = api.mainRef.JData;
    if (!jdata || !jdata.dataJson) return null;
    const dj = jdata.dataJson;
    const det = dj.details;
    if (!det) return null;
    const si = det.signed_images || {};
    const large = si.large || [];
    if (!large.length) return null;
    const dirs = det.directories || {};
    return {
        base_path:     det.base_path || '',
        large_dir:     dirs.large || '',
        signed_images: large,
        title:         dj.title || '',
        description:   dj.description || '',
        pages:         dj.pages || large.length,
        thumbnail:     dj.cover || '',
        slug:          dj.slug || '',
    };
}"""


class YumpuScraper(BaseScraper):
    platform = "yumpu"

    _DOMAIN_RE = re.compile(r"yumpu\.com", re.IGNORECASE)

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    # ──────────────────────────────────────────────────────────────
    #  Entry point
    # ──────────────────────────────────────────────────────────────

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        # ── Yumpu News (subscription) URLs – handle early ────────
        if _YUMPU_NEWS_RE.search(url):
            return await self._scrape_yumpu_news(url)

        doc_id = self._extract_doc_id(url)
        lang = self._extract_lang(url)

        # ── If doc_id not in URL, fetch the page and extract it ──
        html = ""
        if not doc_id:
            logger.info("yumpu_no_url_id", url=url[:120],
                        hint="Fetching HTML to discover document ID")
            html = await self._fetch_html(url)
            doc_id = self._extract_doc_id_from_html(html)

        if not doc_id:
            raise ValueError(
                "Could not extract a document ID from the Yumpu URL. "
                "Please use a URL like: yumpu.com/en/document/read/DOCUMENT_ID/title"
            )

        logger.info("yumpu_scrape_start", doc_id=doc_id, lang=lang)

        # ── Fetch document data from JSON API and process ────────
        api_data = await self._fetch_json_api(doc_id, lang)
        if not html:
            html = await self._fetch_html(url)
        return await self._process_document(doc_id, lang, api_data or {}, url, html)

    # ──────────────────────────────────────────────────────────────
    #  Yumpu News (subscription magazines) – graceful handling
    # ──────────────────────────────────────────────────────────────

    async def _scrape_yumpu_news(self, url: str) -> ScrapedResult:
        """
        Handle Yumpu News magazine/issue URLs.

        1. Resolve the reader URL (``/news/xx/issue/ID-slug/read``).
        2. Load the reader in Playwright and extract the Eagle player's
           ``JData.dataJson.details`` which contains CloudFront-signed
           image URLs for every page at large resolution.
        3. Download all pages and build a PDF.

        Falls back to cover-image preview if Playwright is unavailable
        or the data cannot be extracted.
        """
        logger.info("yumpu_news_detected", url=url[:120])
        html = await self._fetch_html(url)

        title = find_og_tag(html, "og:title") or "Yumpu News Magazine"
        description = find_og_tag(html, "og:description") or ""
        thumbnail = find_og_tag(html, "og:image")
        if thumbnail and thumbnail.startswith("//"):
            thumbnail = "https:" + thumbnail

        # ── Resolve reader URL ───────────────────────────────────
        reader_url: Optional[str] = None

        if _NEWS_READER_RE.search(url):
            # Already a reader URL
            reader_url = url
        else:
            # Magazine listing or issue page → find the reader URL
            is_listing = bool(re.search(r"/magazines/", url, re.I))

            if is_listing:
                # Find the latest issue link on the listing page
                issue_links = re.findall(
                    r'href="(https?://(?:www\.)?yumpu\.com/news/\w+/issue/\d+[^"]*)"',
                    html,
                )
                if issue_links:
                    issue_url = issue_links[0].split("?")[0]
                    logger.info("yumpu_news_latest_issue", issue_url=issue_url[:120])

                    # Update metadata from the issue page
                    issue_html = await self._fetch_html(issue_url)
                    t = find_og_tag(issue_html, "og:title")
                    d = find_og_tag(issue_html, "og:description")
                    th = find_og_tag(issue_html, "og:image")
                    if t:
                        title = t
                    if d:
                        description = d
                    if th:
                        thumbnail = "https:" + th if th.startswith("//") else th

                    # Check if listing has a free doc ID first
                    doc_id = self._extract_doc_id_from_html(issue_html)
                    if doc_id:
                        lang = self._extract_lang(url)
                        api_data = await self._fetch_json_api(doc_id, lang)
                        if api_data:
                            return await self._process_document(
                                doc_id, lang, api_data, issue_url, issue_html,
                            )

                    # Build reader URL from issue URL
                    reader_url = issue_url.rstrip("/") + "/read"
            else:
                # Direct issue URL → check for free doc ID first
                doc_id = self._extract_doc_id_from_html(html)
                if doc_id:
                    lang = self._extract_lang(url)
                    api_data = await self._fetch_json_api(doc_id, lang)
                    if api_data:
                        return await self._process_document(
                            doc_id, lang, api_data, url, html,
                        )

                # Build reader URL
                issue_match = _NEWS_ISSUE_RE.search(url)
                if issue_match:
                    # Reconstruct /read URL from the issue URL
                    base = url.split("?")[0].rstrip("/")
                    if not base.endswith("/read"):
                        reader_url = base + "/read"

        # ── Extract page images from Eagle player ────────────────
        if reader_url:
            logger.info("yumpu_news_reader", url=reader_url[:120])
            eagle_data = await self._extract_eagle_reader_data(reader_url)

            if eagle_data:
                # Prefer the richer og:title from the issue/listing page
                if title and title != "Yumpu News Magazine":
                    eagle_data["og_title"] = title
                if description:
                    eagle_data["og_description"] = description
                if thumbnail:
                    eagle_data["og_thumbnail"] = thumbnail
                return await self._build_news_pdf(eagle_data, url)

        # ── Fallback: cover preview only ─────────────────────────
        logger.warning("yumpu_news_fallback_cover", url=url[:120])
        return self._cover_only_result(title, description, thumbnail)

    # ──────────────────────────────────────────────────────────────
    #  Eagle reader data extraction (Playwright)
    # ──────────────────────────────────────────────────────────────

    async def _extract_eagle_reader_data(self, reader_url: str) -> Optional[dict]:
        """
        Load the Yumpu News reader page in Playwright and extract
        page image data from the Eagle player's JavaScript context.

        Returns a dict with keys:
          base_path, large_dir, signed_images (list), title, pages, thumbnail
        Or None if extraction fails.
        """
        try:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(
                _PW_POOL,
                self._sync_extract_eagle,
                reader_url,
            )
            return data
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("yumpu_eagle_extract_failed",
                         error=repr(e)[:300], exc_type=type(e).__name__,
                         traceback=tb[-600:])
            return None

    @staticmethod
    def _sync_extract_eagle(reader_url: str) -> Optional[dict]:
        """
        Synchronous Playwright extraction of Eagle player data.
        Runs in a thread-pool executor.
        """
        from playwright.sync_api import sync_playwright

        pw = None
        browser = None
        try:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1400, "height": 900})
            page = ctx.new_page()

            logger.info("yumpu_eagle_loading", url=reader_url[:120])
            page.goto(reader_url, timeout=30_000)

            # Wait for the Eagle player to initialise (it loads JS + API data)
            # Poll for the yumpu_eagle_api_0 object to appear
            for attempt in range(20):
                ready = page.evaluate(
                    "() => !!(window.yumpu_eagle_api_0"
                    "  && window.yumpu_eagle_api_0.mainRef"
                    "  && window.yumpu_eagle_api_0.mainRef.JData"
                    "  && window.yumpu_eagle_api_0.mainRef.JData.dataJson"
                    "  && window.yumpu_eagle_api_0.mainRef.JData.dataJson.details"
                    "  && (window.yumpu_eagle_api_0.mainRef.JData.dataJson.details"
                    "      .signed_images || {}).large)"
                )
                if ready:
                    break
                page.wait_for_timeout(500)
            else:
                logger.warning("yumpu_eagle_timeout",
                               hint="Eagle player did not provide signed images in 10s")
                page.close()
                ctx.close()
                return None

            # Extract the data
            data = page.evaluate(_EAGLE_EXTRACT_JS)
            page.close()
            ctx.close()

            if data and data.get("signed_images"):
                count = len(data["signed_images"])
                logger.info("yumpu_eagle_extracted", pages=count,
                            title=data.get("title", "")[:60])
                return data

            return None

        except Exception as e:
            tb = traceback.format_exc()
            logger.error("yumpu_eagle_playwright_err",
                         error=repr(e)[:300], exc_type=type(e).__name__,
                         traceback=tb[-600:])
            return None
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if pw:
                try:
                    pw.stop()
                except Exception:
                    pass

    # ──────────────────────────────────────────────────────────────
    #  Build PDF from Eagle reader data
    # ──────────────────────────────────────────────────────────────

    async def _build_news_pdf(
        self, eagle_data: dict, original_url: str,
    ) -> ScrapedResult:
        """
        Download all page images from the Eagle reader data and
        assemble them into a PDF.
        """
        base_path = eagle_data["base_path"]
        large_dir = eagle_data["large_dir"]
        signed_imgs = eagle_data["signed_images"]
        # Prefer og:title from the issue page (e.g. "Classic Rock - 2026-03-03")
        # over the Eagle data title (which is often just the date)
        title = (
            eagle_data.get("og_title")
            or eagle_data.get("title")
            or "Yumpu News Magazine"
        )
        description = eagle_data.get("og_description") or eagle_data.get("description") or ""
        thumbnail = eagle_data.get("og_thumbnail") or eagle_data.get("thumbnail") or ""
        slug = eagle_data.get("slug") or ""

        # Build full URLs
        image_urls = [
            f"{base_path}/{large_dir}/{signed}"
            for signed in signed_imgs
        ]
        total = min(len(image_urls), _MAX_PAGES)
        image_urls = image_urls[:total]

        logger.info("yumpu_news_pdf_start", pages=total, title=title[:60])

        # Use the shared PDF builder
        doc_id = slug or f"news_{uuid.uuid4().hex[:8]}"
        pdf_path = await self._build_pdf(doc_id, image_urls)

        if not pdf_path:
            # Fall back to cover preview
            return self._cover_only_result(title, description, thumbnail)

        variants: list[ScrapedVariant] = []
        fname = pdf_path.name

        variants.append(ScrapedVariant(
            label="Full Magazine (PDF)",
            format="pdf",
            url=f"/api/files/{fname}",
            file_size_bytes=pdf_path.stat().st_size,
        ))

        # Add individual page previews (first 10)
        for i, img_url in enumerate(image_urls[:10]):
            variants.append(ScrapedVariant(
                label=f"Page {i + 1}",
                format="jpg",
                url=img_url,
            ))

        return ScrapedResult(
            title=title,
            description=description if description else None,
            thumbnail_url=thumbnail if thumbnail else None,
            page_count=total,
            content_type="document",
            variants=variants,
        )

    # ──────────────────────────────────────────────────────────────
    #  Cover-only fallback result
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _cover_only_result(
        title: str, description: str, thumbnail: Optional[str],
    ) -> ScrapedResult:
        """Return a cover-image-only result when full extraction fails."""
        note = (
            "Could not extract the full magazine. "
            "Only the cover image is available for preview."
        )
        variants: list[ScrapedVariant] = []
        if thumbnail:
            variants.append(ScrapedVariant(
                label="Cover Image (preview only)",
                format="jpg",
                url=thumbnail,
            ))
        if not variants:
            raise ValueError(
                "Could not extract content from this Yumpu News page. "
                "The magazine may require a subscriber login."
            )
        return ScrapedResult(
            title=title,
            description=note,
            thumbnail_url=thumbnail,
            content_type="document",
            variants=variants,
        )

    # ──────────────────────────────────────────────────────────────
    #  Shared document processing (used by both normal + news paths)
    # ──────────────────────────────────────────────────────────────

    async def _process_document(
        self,
        doc_id: str,
        lang: str,
        api_data: dict,
        url: str,
        html: str,
    ) -> ScrapedResult:
        """
        Common logic: given a doc_id + API data, build PDF, return result.
        Extracted so both the standard scrape path and the news-fallback
        path can share the same PDF-assembly code.
        """
        document = api_data.get("document", {})
        title = document.get("title") or find_og_tag(html, "og:title") or "Yumpu Document"
        description = document.get("description") or find_og_tag(html, "og:description")
        thumbnail = None

        page_images = self._build_image_urls_from_api(document)

        base_path = document.get("base_path", "")
        images_info = document.get("images", {})
        dims = images_info.get("dimensions", {})
        img_title = images_info.get("title", "")
        thumb_dim = dims.get("small") or dims.get("thumb") or ""
        if base_path and thumb_dim and img_title:
            thumbnail = f"{base_path}1/{thumb_dim}/{img_title}"

        if not page_images:
            # Fallback: try jsonUrl from HTML
            json_url = self._find_json_url_in_html(html)
            if json_url:
                fallback_data = await self._fetch_json_from_url(json_url)
                if fallback_data:
                    fb_doc = fallback_data.get("document", {})
                    if not title or title == "Yumpu Document":
                        title = fb_doc.get("title") or title
                    page_images = self._build_image_urls_from_api(fb_doc)

        if not page_images and not thumbnail:
            og_img = find_og_tag(html, "og:image")
            if og_img:
                thumbnail = "https:" + og_img if og_img.startswith("//") else og_img

        if not page_images and not thumbnail:
            raise ValueError(
                "Could not extract downloadable content from this Yumpu document. "
                "The document may be private or restricted."
            )

        variants: list[ScrapedVariant] = []

        if page_images:
            effective_pages = min(len(page_images), _MAX_PAGES)
            pdf_path = await self._build_pdf(doc_id, page_images[:effective_pages])
            if pdf_path:
                fname = pdf_path.name
                variants.append(ScrapedVariant(
                    label="Full Document (assembled PDF)",
                    format="pdf",
                    url=f"/api/files/{fname}",
                    file_size_bytes=pdf_path.stat().st_size,
                ))
            for i, img_url in enumerate(page_images[:10]):
                variants.append(ScrapedVariant(
                    label=f"Page {i + 1}",
                    format="jpg",
                    url=img_url,
                ))

        if thumbnail and not variants:
            variants.append(ScrapedVariant(
                label="Thumbnail",
                format="jpg",
                url=thumbnail,
            ))

        if not variants:
            raise ValueError(
                "Could not extract downloadable content from this Yumpu document. "
                "The document may be private or restricted."
            )

        return ScrapedResult(
            title=title,
            description=description if description else None,
            thumbnail_url=thumbnail,
            page_count=len(page_images) if page_images else None,
            content_type="document",
            variants=variants,
        )

    # ──────────────────────────────────────────────────────────────
    #  JSON API
    # ──────────────────────────────────────────────────────────────

    async def _fetch_json_api(
        self, doc_id: str, lang: str = "en"
    ) -> Optional[dict]:
        """Fetch document metadata from Yumpu's JSON API."""
        api_url = _JSON_API.format(lang=lang, doc_id=doc_id)
        logger.info("yumpu_api_call", doc_id=doc_id, url=api_url)

        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=20,
                headers={
                    "User-Agent": _UA,
                    "Accept": "application/json, text/javascript, */*",
                    "Referer": f"https://www.yumpu.com/{lang}/document/read/{doc_id}/",
                    "X-Requested-With": "XMLHttpRequest",
                },
            ) as client:
                resp = await client.get(api_url)
                if resp.status_code == 200:
                    data = resp.json()
                    logger.info("yumpu_api_ok", doc_id=doc_id,
                                pages=len(data.get("document", {}).get("pages", [])))
                    return data
                else:
                    logger.warning("yumpu_api_http_error",
                                   status=resp.status_code, doc_id=doc_id)
        except Exception as e:
            logger.warning("yumpu_api_failed", doc_id=doc_id, error=str(e)[:200])

        return None

    async def _fetch_json_from_url(self, json_url: str) -> Optional[dict]:
        """Fetch JSON data from a discovered jsonUrl."""
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=20,
                headers={
                    "User-Agent": _UA,
                    "Accept": "application/json",
                    "Referer": "https://www.yumpu.com/",
                    "X-Requested-With": "XMLHttpRequest",
                },
            ) as client:
                resp = await client.get(json_url)
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            logger.warning("yumpu_json_url_failed", error=str(e)[:200])
        return None

    # ──────────────────────────────────────────────────────────────
    #  Image URL construction from API data
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_image_urls_from_api(document: dict) -> list[str]:
        """
        Build page image URLs from the Yumpu JSON API document structure.

        API returns:
          document.base_path = "https://img.yumpu.com/{doc_id}/"
          document.images.title = "{page_nr}-{url_title}.jpg"
          document.images.dimensions.big = "{width}x{height}"
          document.pages = [{"nr": 1, ...}, {"nr": 2, ...}, ...]

        Image URL pattern:
          {base_path}{page_nr}/{big_dimension}/{page_nr}-{url_title}.jpg
        """
        base_path = document.get("base_path", "")
        if not base_path:
            return []

        images_info = document.get("images", {})
        dims = images_info.get("dimensions", {})
        img_title_template = images_info.get("title", "")

        # Pick the best dimension (big > small > thumb)
        dimension = dims.get("big") or dims.get("small") or dims.get("thumb") or ""
        if not dimension or not img_title_template:
            return []

        pages = document.get("pages", [])
        if not pages:
            return []

        image_urls: list[str] = []
        for page in pages:
            nr = page.get("nr")
            if not nr:
                continue
            # The image title has the page number as a prefix: "1-title.jpg"
            # Replace the leading number to match the current page
            # Title format: "{first_page_nr}-{url_title}.jpg"
            # For page N, it becomes: "{N}-{url_title}.jpg"
            parts = img_title_template.split("-", 1)
            if len(parts) == 2:
                page_title = f"{nr}-{parts[1]}"
            else:
                page_title = img_title_template

            qs = page.get("qs", "")
            url = f"{base_path}{nr}/{dimension}/{page_title}"
            if qs:
                url = f"{url}?{qs}"
            image_urls.append(url)

        return image_urls

    # ──────────────────────────────────────────────────────────────
    #  HTML fetch + fallback extraction
    # ──────────────────────────────────────────────────────────────

    async def _fetch_html(self, url: str) -> str:
        """Fetch Yumpu page HTML (follows redirects)."""
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=20,
                headers={
                    "User-Agent": _UA,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            ) as client:
                resp = await client.get(url)
                return resp.text
        except Exception as e:
            logger.error("yumpu_html_fail", error=str(e)[:120])
            return ""

    @staticmethod
    def _extract_doc_id_from_html(html: str) -> Optional[str]:
        """
        Extract the numeric document ID from Yumpu page HTML.

        Tries multiple sources:
        1. playerConfig.jsonUrl in a <script> tag
        2. img.yumpu.com/{doc_id}/ references
        3. og:url or canonical link with /document/read/{id}/
        """
        if not html:
            return None

        # 1. Look for jsonUrl in playerConfig
        json_url_match = re.search(
            r'"jsonUrl"\s*:\s*"([^"]*?/json[^"]*?/(\d+))"',
            html,
        )
        if json_url_match:
            return json_url_match.group(2)

        # 2. Look for img.yumpu.com/{doc_id}/ pattern
        img_match = re.search(r'img\.yumpu\.com/(\d{5,})/', html)
        if img_match:
            return img_match.group(1)

        # 3. Look in og:url or canonical for /document/{action}/{id}/
        for pattern in [
            r'property="og:url"\s+content="[^"]*?/document/\w+/(\d+)',
            r'rel="canonical"\s+href="[^"]*?/document/\w+/(\d+)',
            r'yumpu\.com/\w+/document/\w+/(\d+)',
        ]:
            m = re.search(pattern, html, re.I)
            if m:
                return m.group(1)

        return None

    @staticmethod
    def _find_json_url_in_html(html: str) -> Optional[str]:
        """Extract the JSON API URL from Yumpu's player config in HTML."""
        m = re.search(r'"jsonUrl"\s*:\s*"([^"]+)"', html)
        if m:
            url = m.group(1).replace("\\/", "/")
            if url.startswith("//"):
                url = "https:" + url
            return url
        return None

    # ──────────────────────────────────────────────────────────────
    #  PDF assembly
    # ──────────────────────────────────────────────────────────────

    async def _build_pdf(
        self, doc_id: str, image_urls: list[str],
    ) -> Optional[Path]:
        """Download all page images and combine into a single PDF."""
        total = len(image_urls)
        logger.info("yumpu_pdf_start", doc_id=doc_id, pages=total)
        start = time.monotonic()

        page_bytes: dict[int, bytes] = {}
        batch_size = 10

        async with httpx.AsyncClient(
            follow_redirects=True, timeout=25,
            headers={
                "User-Agent": _UA,
                "Referer": "https://www.yumpu.com/",
            },
        ) as client:
            for batch_start in range(0, total, batch_size):
                batch_end = min(batch_start + batch_size, total)
                tasks = [
                    self._download_page(client, image_urls[i], i + 1)
                    for i in range(batch_start, batch_end)
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for i, res in zip(range(batch_start, batch_end), results):
                    if isinstance(res, bytes) and len(res) > 100:
                        page_bytes[i] = res
                    else:
                        logger.warning(
                            "yumpu_page_skip",
                            page=i + 1,
                            reason=(
                                str(res)[:80]
                                if isinstance(res, Exception)
                                else "empty"
                            ),
                        )

        if not page_bytes:
            logger.error("yumpu_pdf_no_pages", doc_id=doc_id)
            return None

        ordered = [page_bytes[p] for p in sorted(page_bytes)]

        # Validate & normalise each image for img2pdf
        clean: list[bytes] = []
        for i, raw in enumerate(ordered):
            try:
                img = Image.open(io.BytesIO(raw))
                if img.mode in ("P", "RGBA", "LA"):
                    img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=92)
                clean.append(buf.getvalue())
            except Exception as exc:
                logger.warning("yumpu_img_bad", page=i + 1,
                               err=str(exc)[:80])

        if not clean:
            return None

        fname = f"yumpu_{doc_id}_{uuid.uuid4().hex[:8]}.pdf"
        pdf_path = PDF_DIR / fname
        try:
            pdf_data = img2pdf.convert(clean)
            pdf_path.write_bytes(pdf_data)
            elapsed = time.monotonic() - start
            logger.info(
                "yumpu_pdf_done",
                doc_id=doc_id,
                pages=len(clean),
                size_kb=round(len(pdf_data) / 1024),
                elapsed=round(elapsed, 1),
            )
            return pdf_path
        except Exception as exc:
            logger.error("yumpu_pdf_fail", error=str(exc)[:200])
            return None

    @staticmethod
    async def _download_page(
        client: httpx.AsyncClient, url: str, page_num: int,
    ) -> bytes:
        """Download a single page image."""
        resp = await client.get(url)
        if resp.status_code == 200 and len(resp.content) > 100:
            return resp.content
        raise ValueError(
            f"page {page_num}: HTTP {resp.status_code}, {len(resp.content)}b"
        )

    # ──────────────────────────────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_doc_id(url: str) -> Optional[str]:
        """Extract the numeric document ID from a Yumpu URL."""
        for pattern in _DOC_ID_PATTERNS:
            m = pattern.search(url)
            if m:
                return m.group(1)
        return None

    @staticmethod
    def _extract_lang(url: str) -> str:
        """Extract the language code from the URL (default: en)."""
        m = re.search(r"yumpu\.com/(\w{2})/", url)
        return m.group(1) if m else "en"
