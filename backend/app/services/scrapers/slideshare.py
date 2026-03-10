"""
SlideShare scraper – extracts presentations and documents as PDFs.

Strategy:
  1. Fetch the slideshow page HTML with httpx (no Playwright needed)
  2. Parse ``__NEXT_DATA__`` JSON from the HTML
     → slides.host, slides.imageLocation, slides.imageSizes, totalSlides, title
  3. Build high-quality image URLs for every slide:
     ``{host}/{imageLocation}/{quality}/{title}-{n}-{width}.{format}``
  4. Download all slide images concurrently
  5. Assemble into a single PDF via ``img2pdf``
  6. Serve through ``/api/files/{name}``
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

# Re-use the same temp directory as Scribd for generated PDFs
PDF_DIR = Path(tempfile.gettempdir()) / "extractify_pdfs"
PDF_DIR.mkdir(parents=True, exist_ok=True)

_MAX_SLIDES = 500


class SlideShareScraper(BaseScraper):
    platform = "slideshare"

    _DOMAIN_RE = re.compile(r"slideshare\.net", re.IGNORECASE)

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    # ──────────────────────────────────────────────────────────────
    #  Entry point
    # ──────────────────────────────────────────────────────────────

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        html = await self._fetch_html(url)
        next_data = self._extract_next_data(html)

        if not next_data:
            # Fallback: try OG tags at minimum
            return self._og_fallback(html, url)

        page_props = next_data.get("props", {}).get("pageProps", {})

        # If we got a 404 error page (invalid URL)
        if page_props.get("errorCode") == 404:
            raise ValueError(
                "This SlideShare presentation was not found. "
                "It may have been deleted or the URL is invalid."
            )

        slideshow = page_props.get("slideshow", {})
        if not slideshow:
            return self._og_fallback(html, url)

        title = slideshow.get("title") or "SlideShare Presentation"
        description = slideshow.get("description") or None
        thumbnail = slideshow.get("thumbnail") or None
        total_slides = slideshow.get("totalSlides") or 0
        username = slideshow.get("username") or None
        extension = slideshow.get("extension") or "pptx"
        ss_type = slideshow.get("type") or "presentation"
        slide_dims = slideshow.get("slideDimensions", {})

        # Extract slide image construction data
        slides_data = slideshow.get("slides", {})
        host = slides_data.get("host", "")          # https://image.slidesharecdn.com
        image_location = slides_data.get("imageLocation", "")  # e.g. "slug-date-hash"
        slide_title = slides_data.get("title", "")   # e.g. "Title-formatted"
        image_sizes = slides_data.get("imageSizes", [])
        # imageSizes: [{"quality":85,"width":320,"format":"jpg"}, {"quality":85,"width":638,"format":"jpg"}, {"quality":75,"width":2048,"format":"webp"}]

        variants: list[ScrapedVariant] = []

        # ── Build PDF from slide images ──────────────────────────
        if host and image_location and total_slides > 0:
            # Pick the best quality: prefer 2048 webp or largest jpg
            best_size = self._pick_best_size(image_sizes)
            if best_size:
                effective_slides = min(total_slides, _MAX_SLIDES)
                slide_urls = self._build_slide_urls(
                    host, image_location, slide_title,
                    best_size, effective_slides,
                )
                pdf_path = await self._build_pdf(
                    slideshow.get("id", "ss"),
                    slide_urls,
                    effective_slides,
                )
                if pdf_path:
                    fname = pdf_path.name
                    variants.append(ScrapedVariant(
                        label=f"Full Presentation ({effective_slides} slides)",
                        format="pdf",
                        url=f"/api/files/{fname}",
                        file_size_bytes=pdf_path.stat().st_size,
                    ))

            # Also provide individual slide image variants (first few)
            if image_sizes:
                # Use 638px jpg for individual slide previews
                preview_size = next(
                    (s for s in image_sizes if s.get("width") == 638),
                    image_sizes[0],
                )
                for i in range(1, min(total_slides + 1, 11)):  # max 10 individual slides
                    img_url = self._slide_url(
                        host, image_location, slide_title, preview_size, i
                    )
                    variants.append(ScrapedVariant(
                        label=f"Slide {i}",
                        format=preview_size.get("format", "jpg"),
                        url=img_url,
                    ))

        # Content type
        ct = "presentation" if ss_type == "presentation" else "document"
        if content_tab == "PDFs" or extension == "pdf":
            ct = "pdf"

        if not variants:
            # Last resort: thumbnail as only variant
            if thumbnail:
                variants.append(ScrapedVariant(
                    label="Thumbnail",
                    format="jpg",
                    url=thumbnail,
                ))
            else:
                raise ValueError(
                    "Could not extract slide images from this SlideShare presentation. "
                    "It may be private or behind a paywall."
                )

        return ScrapedResult(
            title=title,
            description=description,
            author=username,
            thumbnail_url=thumbnail,
            page_count=total_slides or None,
            content_type=ct,
            variants=variants,
        )

    # ──────────────────────────────────────────────────────────────
    #  Slide URL construction
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _pick_best_size(image_sizes: list[dict]) -> Optional[dict]:
        """Pick the best image size for PDF assembly.

        SlideShare CDN sometimes reports webp availability but doesn't
        actually serve webp files.  We always request **jpg** instead.
        We pair width with the quality value that SlideShare reports for
        the largest size (usually quality=75 for 2048px).
        """
        if not image_sizes:
            return None
        # Find the entry with the largest width
        biggest = max(image_sizes, key=lambda s: s.get("width", 0))
        # Force jpg format (webp is unreliable on their CDN)
        return {
            "quality": biggest.get("quality", 75),
            "width": biggest.get("width", 2048),
            "format": "jpg",
        }

    @staticmethod
    def _slide_url(
        host: str, image_location: str, slide_title: str,
        size: dict, slide_num: int,
    ) -> str:
        """Build a single slide image URL.

        Pattern: {host}/{imageLocation}/{quality}/{title}-{num}-{width}.{format}
        Example: https://image.slidesharecdn.com/abcdef-230101/85/Title-1-320.jpg
        """
        quality = size.get("quality", 85)
        width = size.get("width", 638)
        fmt = size.get("format", "jpg")
        return f"{host}/{image_location}/{quality}/{slide_title}-{slide_num}-{width}.{fmt}"

    @classmethod
    def _build_slide_urls(
        cls, host: str, image_location: str, slide_title: str,
        size: dict, count: int,
    ) -> list[str]:
        """Build URLs for all slides."""
        return [
            cls._slide_url(host, image_location, slide_title, size, n)
            for n in range(1, count + 1)
        ]

    # ──────────────────────────────────────────────────────────────
    #  PDF assembly (same approach as Scribd)
    # ──────────────────────────────────────────────────────────────

    async def _build_pdf(
        self, ss_id: str, slide_urls: list[str], total: int,
    ) -> Optional[Path]:
        """Download all slide images and combine into a single PDF."""
        logger.info("slideshare_pdf_start", ss_id=ss_id, slides=total)
        start = time.monotonic()

        page_bytes: dict[int, bytes] = {}
        batch_size = 10

        async with httpx.AsyncClient(
            follow_redirects=True, timeout=20,
            headers={"User-Agent": _UA, "Referer": "https://www.slideshare.net/"},
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
                            "slideshare_slide_skip", slide=i + 1,
                            reason=str(res)[:80] if isinstance(res, Exception) else "empty",
                        )

        if not page_bytes:
            logger.error("slideshare_pdf_no_slides", ss_id=ss_id)
            return None

        ordered = [page_bytes[p] for p in sorted(page_bytes)]

        # Normalize images for img2pdf (needs clean JPEG)
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
                logger.warning("slideshare_img_bad", slide=i + 1, err=str(exc)[:80])

        if not clean:
            return None

        fname = f"slideshare_{ss_id}_{uuid.uuid4().hex[:8]}.pdf"
        pdf_path = PDF_DIR / fname
        try:
            pdf_data = img2pdf.convert(clean)
            pdf_path.write_bytes(pdf_data)
            elapsed = time.monotonic() - start
            logger.info(
                "slideshare_pdf_done",
                ss_id=ss_id, slides=len(clean),
                size_kb=round(len(pdf_data) / 1024),
                elapsed=round(elapsed, 1),
            )
            return pdf_path
        except Exception as exc:
            logger.error("slideshare_pdf_fail", error=str(exc)[:200])
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

    @staticmethod
    def _extract_next_data(html: str) -> Optional[dict]:
        """Parse the __NEXT_DATA__ JSON blob from SlideShare HTML."""
        m = re.search(
            r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html, re.S,
        )
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            return None

    async def _fetch_html(self, url: str) -> str:
        """Fetch SlideShare page HTML with httpx."""
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
                # SlideShare returns 404 status for some pages but still
                # serves the full Next.js HTML with __NEXT_DATA__
                return resp.text
        except Exception as e:
            logger.error("slideshare_html_fail", error=str(e)[:120])
            return ""

    def _og_fallback(self, html: str, url: str) -> ScrapedResult:
        """Minimal result from OG tags when __NEXT_DATA__ is missing."""
        title = find_og_tag(html, "og:title") or "SlideShare Presentation"
        description = find_og_tag(html, "og:description")
        thumbnail = find_og_tag(html, "og:image")
        if thumbnail:
            thumbnail = unescape(thumbnail)

        variants = []
        if thumbnail:
            variants.append(ScrapedVariant(
                label="Thumbnail",
                format="jpg",
                url=thumbnail,
            ))

        return ScrapedResult(
            title=unescape(title),
            description=unescape(description) if description else None,
            thumbnail_url=thumbnail,
            content_type="presentation",
            variants=variants,
        )
