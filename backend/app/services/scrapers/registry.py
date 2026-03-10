"""
Scraper registry – maps platform slugs to their scraper class.
"""

from typing import Optional

from app.services.scrapers.base import BaseScraper, ScrapedResult
from app.services.scrapers.instagram import InstagramScraper
from app.services.scrapers.youtube import YouTubeScraper
from app.services.scrapers.facebook import FacebookScraper
from app.services.scrapers.tiktok import TikTokScraper
from app.services.scrapers.twitter import TwitterScraper
from app.services.scrapers.snapchat import SnapchatScraper
from app.services.scrapers.telegram import TelegramScraper
from app.services.scrapers.linkedin import LinkedInScraper
from app.services.scrapers.pinterest import PinterestScraper
from app.services.scrapers.reddit import RedditScraper
from app.services.scrapers.threads import ThreadsScraper
from app.services.scrapers.tumblr import TumblrScraper
from app.services.scrapers.soundcloud import SoundCloudScraper
from app.services.scrapers.generic_social import GenericSocialScraper
from app.services.scrapers.scribd import ScribdScraper
from app.services.scrapers.slideshare import SlideShareScraper
from app.services.scrapers.calameo import CalameoScraper
from app.services.scrapers.yumpu import YumpuScraper
from app.services.scrapers.slideserve import SlideServeScraper
from app.services.scrapers.documents import GenericDocumentScraper


# ── Register all scrapers ────────────────────────────────────────
_SCRAPERS: list[BaseScraper] = [
    InstagramScraper(),
    YouTubeScraper(),
    FacebookScraper(),
    TikTokScraper(),
    TwitterScraper(),
    SnapchatScraper(),
    TelegramScraper(),
    LinkedInScraper(),
    PinterestScraper(),
    RedditScraper(),
    ThreadsScraper(),
    TumblrScraper(),
    SoundCloudScraper(),
    ScribdScraper(),
    SlideShareScraper(),
    CalameoScraper(),
    YumpuScraper(),
    SlideServeScraper(),
    GenericDocumentScraper(),
    GenericSocialScraper(),      # keep last – it's the catch-all
]

# Direct slug → scraper lookup for when we already know the platform
_SLUG_MAP: dict[str, BaseScraper] = {}
for _s in _SCRAPERS:
    if _s.platform != "generic" and _s.platform != "generic_document":
        _SLUG_MAP[_s.platform] = _s


def get_scraper(platform: Optional[str] = None, url: Optional[str] = None) -> BaseScraper:
    """
    Return the appropriate scraper.
    Priority: explicit platform slug → URL-based detection → error.
    """
    # 1. Explicit platform
    if platform and platform in _SLUG_MAP:
        return _SLUG_MAP[platform]

    # 2. URL-based detection
    if url:
        for scraper in _SCRAPERS:
            if scraper.supports(url):
                return scraper

    raise ValueError(f"No scraper found for platform={platform!r}, url={url!r}")


async def run_scraper(
    platform: str,
    url: str,
    content_tab: Optional[str] = None,
) -> ScrapedResult:
    """High-level helper: pick scraper → run → return result."""
    scraper = get_scraper(platform=platform, url=url)
    return await scraper.scrape(url, content_tab)
