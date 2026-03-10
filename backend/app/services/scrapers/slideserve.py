"""
SlideServe scraper – extracts presentations as PDFs.

Strategy:
  1. Fetch the SlideServe page HTML with httpx (no Playwright needed)
  2. Extract the data JS URL from the HTML → fetch JSON with slide metadata
     → bgPath (image base URL), scenes (slide slugs), ext, imgExtns
  3. Build full-resolution image URLs for every slide:
     ``{bgPath}{slug}-l.{ext}`` (``-l`` = large)
  4. Download all slide images concurrently in batches
  5. Assemble into a single PDF via ``img2pdf``
  6. Serve through ``/api/files/{name}``

Fallback: if the data JS is unavailable, scrape image URLs directly from
the ``<ol id="tscript">`` list in the HTML.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import tempfile
import time
import uuid
from html import unescape
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

PDF_DIR = Path(tempfile.gettempdir()) / "extractify_pdfs"
PDF_DIR.mkdir(parents=True, exist_ok=True)

_MAX_SLIDES = 500


class SlideServeScraper(BaseScraper):
    platform = "slideserve"

    _DOMAIN_RE = re.compile(r"slideserve\.com", re.IGNORECASE)

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    # ──────────────────────────────────────────────────────────────
    #  Entry point
    # ──────────────────────────────────────────────────────────────

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        html = await self._fetch_html(url)
        if not html:
            raise ValueError("Failed to fetch SlideServe page.")

        # ── OG metadata ─────────────────────────────────────────
        title = find_og_tag(html, "og:title") or "SlideServe Presentation"
        title = unescape(title)
        description = find_og_tag(html, "og:description")
        if description:
            description = unescape(description)
        thumbnail = find_og_tag(html, "og:image")
        if thumbnail:
            thumbnail = unescape(thumbnail)

        # ── Try structured data from the data JS ────────────────
        doc_data = await self._fetch_doc_data(html)

        slide_urls: list[str] = []
        if doc_data:
            slide_urls = self._build_urls_from_data(doc_data)

        # ── Fallback: scrape image URLs directly from HTML ──────
        if not slide_urls:
            slide_urls = self._scrape_urls_from_html(html)

        if not slide_urls:
            # Last resort: only thumbnail
            variants = []
            if thumbnail:
                variants.append(ScrapedVariant(
                    label="Thumbnail", format="jpg", url=thumbnail,
                ))
            return ScrapedResult(
                title=title,
                description=description,
                thumbnail_url=thumbnail,
                content_type="presentation",
                variants=variants,
            )

        total = len(slide_urls)

        # ── Build PDF ───────────────────────────────────────────
        pdf_path = await self._build_pdf(slide_urls, title)

        variants: list[ScrapedVariant] = []
        if pdf_path:
            fname = pdf_path.name
            variants.append(ScrapedVariant(
                label=f"Full Presentation ({total} slides)",
                format="pdf",
                url=f"/api/files/{fname}",
                file_size_bytes=pdf_path.stat().st_size,
            ))

        # Individual slide previews (first 10)
        for i, img_url in enumerate(slide_urls[:10]):
            variants.append(ScrapedVariant(
                label=f"Slide {i + 1}",
                format="jpg",
                url=img_url,
            ))

        return ScrapedResult(
            title=title,
            description=description,
            thumbnail_url=thumbnail,
            page_count=total,
            content_type="presentation",
            variants=variants,
        )

    # ──────────────────────────────────────────────────────────────
    #  Data JS extraction
    # ──────────────────────────────────────────────────────────────

    async def _fetch_doc_data(self, html: str) -> Optional[dict]:
        """Extract and fetch the structured slide data JS from the HTML.

        The HTML contains a loader like:
          tagLoader.load("https://www.slideserve.com/custom-cache/15/data-xxx.js", ...)
        That JS file defines ``var doc_data = { ... };`` with all slide info.
        """
        m = re.search(
            r'tagLoader\.load\(\s*"(https?://[^"]+/custom-cache/[^"]+\.js)"',
            html,
        )
        if not m:
            logger.debug("slideserve_no_data_js_url")
            return None

        data_url = m.group(1)
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=15,
                headers={"User-Agent": _UA},
            ) as client:
                resp = await client.get(data_url)
                if resp.status_code != 200:
                    logger.warning("slideserve_data_js_http", status=resp.status_code)
                    return None
                js_text = resp.text
        except Exception as e:
            logger.warning("slideserve_data_js_fetch_err", error=repr(e)[:120])
            return None

        # Parse: var doc_data = { ... };
        m2 = re.search(r"var\s+doc_data\s*=\s*(\{.*\})\s*;", js_text, re.S)
        if not m2:
            logger.warning("slideserve_data_js_parse_fail")
            return None

        try:
            data = json.loads(m2.group(1))
            logger.info(
                "slideserve_doc_data",
                slides=len(data.get("scenes", [])),
                bg_path=data.get("bgPath", "")[:60],
            )
            return data
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("slideserve_data_json_err", error=repr(e)[:120])
            return None

    @staticmethod
    def _build_urls_from_data(doc_data: dict) -> list[str]:
        """Build full-resolution slide URLs from the structured data.

        Data shape:
          { "scenes": [{"bg": "slug"}, ...],
            "bgPath": "https://image9.slideserve.com/14784023/",
            "ext": "jpg",
            "imgExtns": "t,n,l" }

        URL pattern: {bgPath}{slug}-l.{ext}  (``-l`` = large)
        """
        scenes = doc_data.get("scenes", [])
        bg_path = doc_data.get("bgPath", "").rstrip("/")
        ext = doc_data.get("ext", "jpg")
        img_extns = doc_data.get("imgExtns", "t,n,l")

        if not scenes or not bg_path:
            return []

        # Pick the largest available size suffix
        # imgExtns is comma-separated: "t,n,l" → t=thumbnail, n=normal, l=large
        size_suffix = "l"  # large by default
        if "l" not in img_extns.split(","):
            # Fall back to whatever is available
            parts = img_extns.split(",")
            size_suffix = parts[-1] if parts else "l"

        urls = []
        for scene in scenes[:_MAX_SLIDES]:
            slug = scene.get("bg", "")
            if slug:
                urls.append(f"{bg_path}/{slug}-{size_suffix}.{ext}")

        return urls

    @staticmethod
    def _scrape_urls_from_html(html: str) -> list[str]:
        """Fallback: extract image URLs from the <ol id='tscript'> list
        or from any image*.slideserve.com references in the HTML."""
        # Try structured list first
        tscript = re.search(r'<ol\s+id=["\']tscript["\']>(.*?)</ol>', html, re.S)
        if tscript:
            urls = re.findall(
                r'href="(https://image\d*\.slideserve\.com/[^"]+)"',
                tscript.group(1),
            )
            if urls:
                return list(dict.fromkeys(urls))  # deduplicate, preserve order

        # Broader regex fallback
        imgs = re.findall(
            r'https://image\d*\.slideserve\.com/\d+/[^\s"\'<>]+-l\.(?:jpg|png)',
            html,
        )
        return list(dict.fromkeys(imgs))

    # ──────────────────────────────────────────────────────────────
    #  PDF assembly
    # ──────────────────────────────────────────────────────────────

    async def _build_pdf(
        self, slide_urls: list[str], title: str,
    ) -> Optional[Path]:
        """Download all slide images and combine into a single PDF."""
        total = len(slide_urls)
        logger.info("slideserve_pdf_start", slides=total, title=title[:60])
        start = time.monotonic()

        page_bytes: dict[int, bytes] = {}
        batch_size = 10

        async with httpx.AsyncClient(
            follow_redirects=True, timeout=20,
            headers={
                "User-Agent": _UA,
                "Referer": "https://www.slideserve.com/",
            },
        ) as client:
            for batch_start in range(0, total, batch_size):
                batch_end = min(batch_start + batch_size, total)
                tasks = [
                    self._download_slide(client, slide_urls[i], i + 1)
                    for i in range(batch_start, batch_end)
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for i, res in zip(range(batch_start, batch_end), results):
                    if isinstance(res, bytes) and len(res) > 100:
                        page_bytes[i] = res
                    else:
                        logger.warning(
                            "slideserve_slide_skip", slide=i + 1,
                            reason=str(res)[:80] if isinstance(res, Exception) else "empty",
                        )

        if not page_bytes:
            logger.error("slideserve_pdf_no_slides")
            return None

        ordered = [page_bytes[p] for p in sorted(page_bytes)]

        # Normalize images for img2pdf
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
                logger.warning("slideserve_img_bad", slide=i + 1, err=str(exc)[:80])

        if not clean:
            return None

        fname = f"slideserve_{uuid.uuid4().hex[:8]}.pdf"
        pdf_path = PDF_DIR / fname
        try:
            pdf_data = img2pdf.convert(clean)
            pdf_path.write_bytes(pdf_data)
            elapsed = time.monotonic() - start
            logger.info(
                "slideserve_pdf_done",
                slides=len(clean),
                size_kb=round(len(pdf_data) / 1024),
                elapsed=round(elapsed, 1),
            )
            return pdf_path
        except Exception as exc:
            logger.error("slideserve_pdf_fail", error=str(exc)[:200])
            return None

    @staticmethod
    async def _download_slide(
        client: httpx.AsyncClient, url: str, n: int,
    ) -> bytes:
        resp = await client.get(url)
        if resp.status_code == 200 and len(resp.content) > 100:
            return resp.content
        raise ValueError(f"slide {n}: HTTP {resp.status_code}, {len(resp.content)}b")

    # ──────────────────────────────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────────────────────────────

    async def _fetch_html(self, url: str) -> str:
        """Fetch SlideServe page HTML."""
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
            logger.error("slideserve_html_fail", error=repr(e)[:120])
            return ""
