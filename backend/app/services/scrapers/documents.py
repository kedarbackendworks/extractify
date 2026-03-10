"""
Generic document-platform scraper – covers SlideShare, Issuu,
Calameo, Yumpu, SlideServe.

These platforms render documents as page images in a JS reader.
Strategy: extract page images via Playwright, assemble into PDF.
"""

import re
from typing import Optional

from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.utils.browser import get_page_content


class GenericDocumentScraper(BaseScraper):
    """Handles SlideShare, Issuu, Calameo, Yumpu, SlideServe."""

    platform = "generic_document"

    _SUPPORTED: dict[str, str] = {
        # SlideShare now has its own dedicated scraper (slideshare.py)
        "issuu.com": "issuu",

        # SlideServe now has its own dedicated scraper (slideserve.py)
    }

    def supports(self, url: str) -> bool:
        return any(domain in url for domain in self._SUPPORTED)

    def _detect_platform(self, url: str) -> str:
        for domain, plat in self._SUPPORTED.items():
            if domain in url:
                return plat
        return "document"

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        detected = self._detect_platform(url)
        html = await get_page_content(url)

        import re as _re

        # ── Common OG metadata extraction ────────────────────────
        title_match = _re.search(r'property="og:title"\s+content="([^"]*)"', html)
        desc_match = _re.search(r'property="og:description"\s+content="([^"]*)"', html)
        thumb_match = _re.search(r'property="og:image"\s+content="([^"]*)"', html)

        # ── Platform-specific page image extraction ──────────────
        page_images = []

        if detected == "slideshare":
            # SlideShare renders slides as images
            page_images = _re.findall(
                r'https://image\.slidesharecdn\.com/[^\s"\']+\.(?:jpg|png|webp)',
                html,
            )
        elif detected == "issuu":
            # Issuu page images
            page_images = _re.findall(
                r'https://[^"\'\s]+\.issu\.com/[^"\'\s]+\.(?:jpg|png|webp)',
                html,
            )
            if not page_images:
                page_images = _re.findall(
                    r'https://image\.issuu\.com/[^"\'\s]+\.(?:jpg|png)',
                    html,
                )
        elif detected == "calameo":
            page_images = _re.findall(
                r'https://[^"\'\s]*calameo[^"\'\s]+\.(?:jpg|png|svgz?)',
                html,
            )
        elif detected == "yumpu":
            page_images = _re.findall(
                r'https://[^"\'\s]+\.yumpu\.com/[^"\'\s]+\.(?:jpg|png)',
                html,
            )
        elif detected == "slideserve":
            page_images = _re.findall(
                r'https://[^"\'\s]+\.slideserve\.com/[^"\'\s]+\.(?:jpg|png)',
                html,
            )

        # Deduplicate while preserving order
        seen = set()
        unique_images = []
        for img in page_images:
            if img not in seen:
                seen.add(img)
                unique_images.append(img)
        page_images = unique_images

        # ── Build variants ───────────────────────────────────────
        variants = []
        if page_images:
            variants.append(ScrapedVariant(
                label="Full Document (assembled PDF)",
                format="pdf",
                url=page_images[0],  # Placeholder; actual assembly in worker
                quality="original",
            ))

        for i, img_url in enumerate(page_images[:10]):
            variants.append(ScrapedVariant(
                label=f"Page {i + 1}",
                format="jpg",
                url=img_url,
            ))

        content_type = "presentation" if detected in ("slideshare", "slideserve") else "document"

        return ScrapedResult(
            title=title_match.group(1) if title_match else f"{detected.title()} Document",
            description=desc_match.group(1) if desc_match else None,
            thumbnail_url=thumb_match.group(1) if thumb_match else None,
            page_count=len(page_images) if page_images else None,
            content_type=content_type,
            variants=variants,
        )
