"""
Telegram scraper – public channel posts.
Uses t.me embed pages + Playwright for JS-rendered content.
"""

import re
from typing import Optional

import httpx
from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.utils.browser import get_page_content


class TelegramScraper(BaseScraper):
    platform = "telegram"

    _DOMAIN_RE = re.compile(r"(t\.me|telegram\.org)")

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        # t.me/channel/123 → t.me/channel/123?embed=1 gives cleaner HTML
        embed_url = url.rstrip("/") + "?embed=1"
        html = await get_page_content(embed_url)

        import re as _re
        variants = []
        title = "Telegram Post"
        content_type = "other"

        # Look for video source
        video_match = _re.search(r'<video[^>]+src="([^"]+)"', html)
        if video_match:
            variants.append(ScrapedVariant(label="Video", format="mp4", url=video_match.group(1)))
            content_type = "video"

        # Look for images
        images = _re.findall(r'background-image:\s*url\([\'"]?([^\'")]+)', html)
        for i, img in enumerate(images):
            variants.append(ScrapedVariant(label=f"Image {i+1}", format="jpg", url=img))
            if content_type == "other":
                content_type = "image"

        # Look for file downloads (documents)
        doc_match = _re.search(r'href="([^"]+)"[^>]*class="[^"]*tgme_widget_message_document_title', html)
        if doc_match:
            variants.append(ScrapedVariant(label="Document", format="pdf", url=doc_match.group(1)))
            content_type = "document"

        # Extract title from message text
        text_match = _re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', html, _re.DOTALL)
        if text_match:
            from html import unescape
            raw = _re.sub(r'<[^>]+>', '', text_match.group(1))
            title = unescape(raw)[:120].strip() or title

        return ScrapedResult(
            title=title,
            content_type=content_type,
            variants=variants,
        )
