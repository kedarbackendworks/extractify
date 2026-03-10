"""
Scribd scraper – extracts documents, PDFs, and audiobooks.

Strategy (documents):
  1. Fetch ``/documents/{doc_id}.json`` public API → page_count, generated_image_url
  2. Download every page image from ``{generated_image_url}{page_num}`` (768×1024 JPEG)
  3. Assemble all page images into a single PDF via ``img2pdf``
  4. Serve the PDF through ``/api/files/{name}`` and return it as the primary variant
  5. Fall back to OG-tag thumbnail when the JSON API is unavailable

Audiobooks are DRM-protected; only metadata is returned.
"""

from __future__ import annotations

import asyncio
import io
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

# Directory where generated PDFs are stored
PDF_DIR = Path(tempfile.gettempdir()) / "extractify_pdfs"
PDF_DIR.mkdir(parents=True, exist_ok=True)

# Maximum pages we will attempt to download (safety guard)
_MAX_PAGES = 500


class ScribdScraper(BaseScraper):
    platform = "scribd"

    _DOMAIN_RE = re.compile(r"scribd\.com")

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    # ──────────────────────────────────────────────────────────────
    #  Entry point
    # ──────────────────────────────────────────────────────────────

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        if content_tab == "Audiobooks" or "/audiobook/" in url:
            return await self._scrape_audiobook(url)
        return await self._scrape_document(url, content_tab)

    # ──────────────────────────────────────────────────────────────
    #  Document / PDF extraction
    # ──────────────────────────────────────────────────────────────

    async def _scrape_document(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        doc_id = self._extract_doc_id(url)
        if not doc_id:
            raise ValueError("Could not extract a document ID from the Scribd URL.")

        # ── 1. Get document metadata from public JSON API ────────
        meta = await self._fetch_doc_json(doc_id)
        title = meta.get("title") or "Scribd Document"
        page_count = meta.get("page_count") or 0
        gen_img_url = meta.get("generated_image_url") or ""
        thumbnail = meta.get("thumbnail_url") or None
        author = None
        user = meta.get("user")
        if isinstance(user, dict):
            author = user.get("name")

        variants: list[ScrapedVariant] = []

        # ── 2. Build PDF from page images ────────────────────────
        if gen_img_url and page_count and page_count > 0:
            effective_pages = min(page_count, _MAX_PAGES)
            pdf_path = await self._build_pdf(doc_id, gen_img_url, effective_pages)
            if pdf_path:
                fname = pdf_path.name
                variants.append(ScrapedVariant(
                    label=f"Full Document ({effective_pages} pages)",
                    format="pdf",
                    url=f"/api/files/{fname}",
                    file_size_bytes=pdf_path.stat().st_size,
                ))

        # ── 3. Fallback / supplement: OG-tag thumbnail ───────────
        if not thumbnail:
            html = await self._fetch_html(url)
            thumbnail = find_og_tag(html, "og:image")
            if thumbnail:
                thumbnail = unescape(thumbnail)
            if not title or title == "Scribd Document":
                og_title = find_og_tag(html, "og:title")
                if og_title:
                    title = unescape(og_title)

        if thumbnail and thumbnail.startswith("http"):
            variants.append(ScrapedVariant(
                label="Thumbnail",
                format="jpg",
                url=thumbnail,
            ))

        ct = "pdf" if ("pdf" in url.lower() or content_tab == "PDFs") else "document"

        if not variants:
            raise ValueError(
                "Could not extract downloadable content from this Scribd document. "
                "It may be fully behind the Scribd paywall."
            )

        return ScrapedResult(
            title=title,
            author=author,
            thumbnail_url=thumbnail,
            page_count=page_count or None,
            content_type=ct,
            variants=variants,
        )

    # ──────────────────────────────────────────────────────────────
    #  Audiobook (metadata only — DRM protected)
    # ──────────────────────────────────────────────────────────────

    async def _scrape_audiobook(self, url: str) -> ScrapedResult:
        html = await self._fetch_html(url)

        title = unescape(find_og_tag(html, "og:title") or "") or "Scribd Audiobook"
        thumbnail = find_og_tag(html, "og:image")
        if thumbnail:
            thumbnail = unescape(thumbnail)
        author_m = re.search(r'"author"\s*:\s*"([^"]*)"', html)
        author = unescape(author_m.group(1)) if author_m else None

        return ScrapedResult(
            title=title,
            author=author,
            thumbnail_url=thumbnail,
            content_type="audio",
            variants=[],
        )

    # ──────────────────────────────────────────────────────────────
    #  Core: JSON API + PDF assembly
    # ──────────────────────────────────────────────────────────────

    async def _fetch_doc_json(self, doc_id: str) -> dict:
        """``GET /documents/{doc_id}.json`` – public, no auth needed."""
        url = f"https://www.scribd.com/documents/{doc_id}.json"
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=15,
                headers={"User-Agent": _UA, "Accept": "application/json"},
            ) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    logger.info("scribd_json_api",
                                doc_id=doc_id,
                                pages=data.get("page_count"),
                                title=str(data.get("title", ""))[:60])
                    return data
                logger.warning("scribd_json_api_status", status=resp.status_code)
        except Exception as exc:
            logger.warning("scribd_json_api_fail", error=str(exc)[:120])
        return {}

    async def _build_pdf(
        self, doc_id: str, gen_img_base: str, page_count: int
    ) -> Optional[Path]:
        """Download all page images and combine them into a PDF."""
        if not gen_img_base.endswith("/"):
            gen_img_base += "/"

        logger.info("scribd_pdf_start", doc_id=doc_id, pages=page_count)
        start = time.monotonic()

        page_bytes: dict[int, bytes] = {}
        batch_size = 10

        async with httpx.AsyncClient(
            follow_redirects=True, timeout=20, headers={"User-Agent": _UA},
        ) as client:
            for batch_start in range(1, page_count + 1, batch_size):
                batch_end = min(batch_start + batch_size, page_count + 1)
                tasks = [
                    self._download_page(client, f"{gen_img_base}{n}", n)
                    for n in range(batch_start, batch_end)
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for n, res in zip(range(batch_start, batch_end), results):
                    if isinstance(res, bytes) and len(res) > 100:
                        page_bytes[n] = res
                    else:
                        logger.warning("scribd_page_skip", page=n,
                                       reason=str(res)[:80] if isinstance(res, Exception) else "empty")

        if not page_bytes:
            logger.error("scribd_pdf_no_pages", doc_id=doc_id)
            return None

        ordered = [page_bytes[p] for p in sorted(page_bytes)]

        # Validate & normalise each image (img2pdf needs clean JPEG)
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
                logger.warning("scribd_img_bad", page=i + 1, err=str(exc)[:80])

        if not clean:
            return None

        fname = f"scribd_{doc_id}_{uuid.uuid4().hex[:8]}.pdf"
        pdf_path = PDF_DIR / fname
        try:
            pdf_data = img2pdf.convert(clean)
            pdf_path.write_bytes(pdf_data)
            elapsed = time.monotonic() - start
            logger.info("scribd_pdf_done",
                        doc_id=doc_id, pages=len(clean),
                        size_kb=round(len(pdf_data) / 1024),
                        elapsed=round(elapsed, 1))
            return pdf_path
        except Exception as exc:
            logger.error("scribd_pdf_fail", error=str(exc)[:200])
            return None

    @staticmethod
    async def _download_page(client: httpx.AsyncClient, url: str, n: int) -> bytes:
        resp = await client.get(url)
        if resp.status_code == 200 and len(resp.content) > 100:
            return resp.content
        raise ValueError(f"page {n}: HTTP {resp.status_code}, {len(resp.content)}b")

    # ──────────────────────────────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_doc_id(url: str) -> Optional[str]:
        m = re.search(r"/(?:document|doc|read|book|presentation)/(\d+)", url)
        return m.group(1) if m else None

    async def _fetch_html(self, url: str) -> str:
        """Lightweight HTML fetch for OG-tag fallback."""
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=15,
                headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"},
            ) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.text
        except Exception as e:
            logger.debug("scribd_html_fail", error=str(e)[:80])
        return ""

