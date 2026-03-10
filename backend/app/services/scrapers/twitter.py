"""
Twitter / X scraper – authenticated GraphQL media extraction.

Strategy priority:
  1. Twitter GraphQL API  (uses auth cookies, handles photos + videos + GIFs)
  2. yt-dlp with cookies  (fallback for video tweets)
  3. FxTwitter API        (legacy fallback for old/public tweets)
"""

import json
import logging
import re
from typing import Optional

import httpx
from app.core.config import settings
from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.services.scrapers.helpers import build_ytdlp_variants
from app.utils.ytdlp_helper import extract_with_ytdlp

logger = logging.getLogger(__name__)

# ── Twitter API constants ────────────────────────────────────────


def _get_bearer() -> str:
    """Return the Twitter bearer token from TWITTER_BEARER_TOKEN env var."""
    tok = settings.TWITTER_BEARER_TOKEN
    if not tok:
        raise RuntimeError("TWITTER_BEARER_TOKEN is not set")
    return tok

_GRAPHQL_ENDPOINT = (
    "https://x.com/i/api/graphql/"
    "2ICDjqPd81tulZcYrtpTuQ/TweetResultByRestId"
)

_GRAPHQL_FEATURES = {
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
    "responsive_web_media_download_video_enabled": True,
    "premium_content_api_read_enabled": False,
    "tweetypie_unmention_optimization_enabled": True,
}

_TWEET_ID_RE = re.compile(r"/status(?:es)?/(\d+)")


class TwitterScraper(BaseScraper):
    platform = "twitter"

    _DOMAIN_RE = re.compile(r"(twitter\.com|x\.com)")

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _extract_tweet_id(url: str) -> Optional[str]:
        m = _TWEET_ID_RE.search(url)
        return m.group(1) if m else None

    def _has_auth(self) -> bool:
        return bool(settings.TWITTER_AUTH_TOKEN and settings.TWITTER_CSRF_TOKEN)

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {_get_bearer()}",
            "Cookie": (
                f"auth_token={settings.TWITTER_AUTH_TOKEN}; "
                f"ct0={settings.TWITTER_CSRF_TOKEN}; lang=en"
            ),
            "x-csrf-token": settings.TWITTER_CSRF_TOKEN,
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-client-language": "en",
            "x-twitter-active-user": "yes",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Referer": "https://x.com/",
            "Origin": "https://x.com",
            "Accept": "*/*",
        }

    # ── Main entry ───────────────────────────────────────────────

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        # ── Strategy 1: Authenticated GraphQL API ────────────────
        if self._has_auth():
            try:
                result = await self._scrape_graphql(url, content_tab)
                if result and result.variants:
                    return result
            except Exception as exc:
                logger.warning("Twitter GraphQL failed: %s", exc)

        # ── Strategy 2: yt-dlp with cookies ──────────────────────
        if content_tab != "Images":
            try:
                info = await extract_with_ytdlp(url)
                variants = build_ytdlp_variants(info)
                if variants:
                    return ScrapedResult(
                        title=info.get("title"),
                        description=info.get("description"),
                        author=info.get("uploader"),
                        thumbnail_url=info.get("thumbnail"),
                        duration_seconds=info.get("duration"),
                        content_type="video",
                        variants=variants,
                    )
            except Exception:
                pass

        # ── Strategy 3: FxTwitter (old/public tweets) ────────────
        try:
            result = await self._scrape_fxtwitter(url)
            if result and result.variants:
                if content_tab == "Images":
                    img = [v for v in result.variants if not v.has_video]
                    if img:
                        result.variants = img
                        result.content_type = "image"
                return result
        except Exception:
            pass

        raise ValueError(
            "Could not extract this tweet. "
            "It may be private, deleted, or require authentication."
        )

    # ── Strategy 1: GraphQL API ──────────────────────────────────

    async def _scrape_graphql(
        self, url: str, content_tab: Optional[str] = None
    ) -> Optional[ScrapedResult]:
        tweet_id = self._extract_tweet_id(url)
        if not tweet_id:
            return None

        variables = json.dumps(
            {
                "tweetId": tweet_id,
                "withCommunity": False,
                "includePromotedContent": False,
                "withVoice": False,
            },
            separators=(",", ":"),
        )
        features = json.dumps(_GRAPHQL_FEATURES, separators=(",", ":"))
        field_toggles = json.dumps(
            {"withArticleRichContentState": False}, separators=(",", ":")
        )

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                _GRAPHQL_ENDPOINT,
                headers=self._build_headers(),
                params={
                    "variables": variables,
                    "features": features,
                    "fieldToggles": field_toggles,
                },
            )

        if resp.status_code != 200:
            logger.warning("GraphQL HTTP %s", resp.status_code)
            return None

        data = resp.json()

        # Navigate the response tree
        result = (
            data.get("data", {}).get("tweetResult", {}).get("result", {})
        )
        if not result:
            errors = data.get("errors", [])
            if errors:
                msg = errors[0].get("message", "")
                logger.warning("GraphQL error: %s", msg)
            return None

        # Handle visibility-wrapped tweets
        if result.get("__typename") == "TweetWithVisibilityResults":
            result = result.get("tweet", result)

        legacy = result.get("legacy", {})
        core = result.get("core", {})
        user = (
            core.get("user_results", {})
            .get("result", {})
            .get("legacy", {})
        )

        full_text = legacy.get("full_text", "")
        author_name = user.get("name") or user.get("screen_name") or ""

        # Extract media from extended_entities (preferred) or entities
        media_list = (
            legacy.get("extended_entities", {}).get("media", [])
            or legacy.get("entities", {}).get("media", [])
        )

        variants: list[ScrapedVariant] = []
        thumbnail: Optional[str] = None
        last_video_info: dict = {}

        for item in media_list:
            media_type = item.get("type", "photo")
            media_url = item.get("media_url_https") or item.get("media_url", "")

            if not thumbnail and media_url:
                thumbnail = media_url

            if media_type == "photo":
                if content_tab and content_tab not in ("Images", "Photos"):
                    continue
                orig_url = (
                    f"{media_url}?format=jpg&name=orig"
                    if "?" not in media_url
                    else media_url
                )
                variants.append(
                    ScrapedVariant(
                        label=f"Image {len(variants) + 1}",
                        format="jpg",
                        url=orig_url,
                    )
                )

            elif media_type in ("video", "animated_gif"):
                if content_tab == "Images":
                    continue
                video_info = item.get("video_info", {})
                last_video_info = video_info
                vid_variants = video_info.get("variants", [])

                # MP4 variants sorted by bitrate (highest first)
                mp4s = [
                    v for v in vid_variants
                    if v.get("content_type") == "video/mp4"
                ]
                mp4s.sort(key=lambda v: v.get("bitrate", 0), reverse=True)

                for v in mp4s:
                    bitrate = v.get("bitrate", 0)
                    vid_url = v.get("url", "")
                    if not vid_url:
                        continue

                    if bitrate >= 2_000_000:
                        label = "1080p"
                    elif bitrate >= 800_000:
                        label = "720p"
                    elif bitrate >= 400_000:
                        label = "480p"
                    elif bitrate >= 200_000:
                        label = "360p"
                    else:
                        label = f"{bitrate // 1000}kbps" if bitrate else "Video"

                    duration_ms = video_info.get("duration_millis", 0)
                    size = (
                        int(bitrate * duration_ms / 8000)
                        if bitrate and duration_ms
                        else None
                    )

                    variants.append(
                        ScrapedVariant(
                            label=label if media_type == "video" else "GIF",
                            format="mp4",
                            url=vid_url,
                            has_video=True,
                            has_audio=media_type == "video",
                            file_size_bytes=size,
                        )
                    )

        if not variants:
            return None

        content_type = "video" if any(v.has_video for v in variants) else "image"

        duration_secs = None
        if last_video_info.get("duration_millis"):
            duration_secs = last_video_info["duration_millis"] / 1000

        return ScrapedResult(
            title=(full_text[:120] or "Tweet").strip(),
            description=full_text,
            author=author_name,
            thumbnail_url=thumbnail,
            duration_seconds=duration_secs,
            content_type=content_type,
            variants=variants,
        )

    # ── Strategy 3: FxTwitter API (legacy fallback) ──────────────

    async def _scrape_fxtwitter(self, url: str) -> Optional[ScrapedResult]:
        api_url = re.sub(
            r"https?://(twitter\.com|x\.com)",
            "https://api.fxtwitter.com",
            url,
        )

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(api_url)
            resp.raise_for_status()
            data = resp.json()

        tweet = data.get("tweet")
        if not tweet:
            return None

        variants: list[ScrapedVariant] = []
        thumbnail: Optional[str] = None
        media = tweet.get("media") or {}

        for i, photo in enumerate(media.get("photos") or []):
            photo_url = photo.get("url")
            if photo_url:
                if not thumbnail:
                    thumbnail = photo_url
                orig_url = (
                    f"{photo_url}?format=jpg&name=orig"
                    if "?" not in photo_url
                    else photo_url
                )
                variants.append(
                    ScrapedVariant(
                        label=f"Image {i + 1}" if len(media.get("photos", [])) > 1 else "Image",
                        format="jpg",
                        url=orig_url,
                    )
                )

        for vid in media.get("videos") or []:
            vid_url = vid.get("url")
            if vid_url:
                if not thumbnail:
                    thumbnail = vid.get("thumbnail_url")
                height = vid.get("height")
                variants.append(
                    ScrapedVariant(
                        label=f"{height}p" if height else "Video",
                        format="mp4",
                        url=vid_url,
                        has_video=True,
                        has_audio=True,
                    )
                )

        if not variants:
            for i, m in enumerate(media.get("all") or []):
                m_url = m.get("url")
                m_type = m.get("type", "photo")
                if not m_url:
                    continue
                if m_type in ("video", "gif"):
                    variants.append(
                        ScrapedVariant(
                            label="Video" if m_type == "video" else "GIF",
                            format="mp4",
                            url=m_url,
                            has_video=True,
                            has_audio=m_type == "video",
                        )
                    )
                else:
                    if not thumbnail:
                        thumbnail = m_url
                    variants.append(
                        ScrapedVariant(label=f"Image {i + 1}", format="jpg", url=m_url)
                    )

        if not variants:
            return None

        author_data = tweet.get("author") or {}
        content_type = "video" if any(v.has_video for v in variants) else "image"

        return ScrapedResult(
            title=(tweet.get("text") or "")[:120] or "Tweet",
            description=tweet.get("text"),
            author=author_data.get("name") or author_data.get("screen_name"),
            thumbnail_url=thumbnail,
            content_type=content_type,
            variants=variants,
        )
