"""
SoundCloud scraper – downloads audio tracks, playlists, podcasts, and waveforms.

Strategies (in priority order):
  1. SoundCloud API v2   (primary – fresh client_id from JS bundles)
  2. yt-dlp              (fallback – may have stale client_id)
  3. SoundCloud oEmbed   (metadata fallback for title/thumbnail)
  4. HTML OG-tag parsing  (last-resort metadata)

Supports:
  - Single tracks       soundcloud.com/<user>/<track>
  - Playlists / Sets    soundcloud.com/<user>/sets/<set>
  - User tracks         soundcloud.com/<user>/tracks
  - Podcasts            soundcloud.com/<user>/<episode>  (same as track)
  - Likes / Reposts     soundcloud.com/<user>/likes
  - Waveform images     extracted from track metadata
"""

import json
import re
import time
from typing import List, Optional
from urllib.parse import quote, urlparse

import httpx
import structlog

from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant
from app.services.scrapers.helpers import find_og_tag
from app.utils.ytdlp_helper import extract_with_ytdlp

logger = structlog.get_logger()

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

_SC_API_BASE = "https://api-v2.soundcloud.com"

# ── Client-ID cache (shared across scraper instances) ───────────
_cached_client_id: Optional[str] = None
_client_id_fetched_at: float = 0
_CLIENT_ID_TTL = 3600  # re-fetch after 1 hour


class SoundCloudScraper(BaseScraper):
    platform = "soundcloud"

    _DOMAIN_RE = re.compile(r"soundcloud\.com")

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    # ── Client-ID extraction ────────────────────────────────────

    @staticmethod
    async def _get_client_id() -> Optional[str]:
        """Extract a fresh client_id from SoundCloud's JS bundles (cached)."""
        global _cached_client_id, _client_id_fetched_at

        if _cached_client_id and (time.time() - _client_id_fetched_at) < _CLIENT_ID_TTL:
            return _cached_client_id

        try:
            async with httpx.AsyncClient(
                timeout=15, follow_redirects=True, headers=_HEADERS,
            ) as client:
                resp = await client.get("https://soundcloud.com")
                resp.raise_for_status()

                scripts = re.findall(
                    r'src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"',
                    resp.text,
                )

                # Search bundles in reverse (app bundles with client_id are last)
                for script_url in reversed(scripts):
                    try:
                        js_resp = await client.get(script_url)
                        match = re.search(
                            r'client_id\s*[:=]\s*"([a-zA-Z0-9]{32})"',
                            js_resp.text,
                        )
                        if match:
                            _cached_client_id = match.group(1)
                            _client_id_fetched_at = time.time()
                            logger.debug(
                                "soundcloud_client_id_extracted",
                                client_id=_cached_client_id[:8] + "...",
                            )
                            return _cached_client_id
                    except Exception:
                        continue
        except Exception as exc:
            logger.debug("soundcloud_client_id_failed", error=str(exc)[:200])

        return _cached_client_id  # return stale if fresh fetch failed

    # ── API v2 helpers ──────────────────────────────────────────

    async def _api_resolve(self, url: str, client_id: str) -> Optional[dict]:
        """Resolve a SoundCloud URL via API v2."""
        api_url = f"{_SC_API_BASE}/resolve?url={quote(url, safe='')}&client_id={client_id}"
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, headers=_HEADERS,
        ) as client:
            resp = await client.get(api_url)
            if resp.status_code != 200:
                return None
            return resp.json()

    async def _api_get_stream_url(
        self, stream_api_url: str, client_id: str, track_auth: str = "",
        http: Optional[httpx.AsyncClient] = None,
    ) -> Optional[str]:
        """Fetch the actual stream URL from a transcoding endpoint."""
        url = f"{stream_api_url}?client_id={client_id}"
        if track_auth:
            url += f"&track_authorization={track_auth}"
        try:
            if http:
                resp = await http.get(url)
            else:
                async with httpx.AsyncClient(
                    timeout=10, follow_redirects=True, headers=_HEADERS,
                ) as client:
                    resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("url")
        except Exception as exc:
            logger.debug("soundcloud_stream_url_failed", error=str(exc)[:200])
        return None

    def _build_variants_from_track_data(
        self, track: dict, stream_urls: dict,
    ) -> list[ScrapedVariant]:
        """Build download variants from API v2 track data + resolved stream URLs."""
        variants: list[ScrapedVariant] = []

        media = track.get("media", {})
        transcodings = media.get("transcodings", [])

        for tc in transcodings:
            fmt = tc.get("format", {})
            protocol = fmt.get("protocol", "")
            mime = fmt.get("mime_type", "")
            preset = tc.get("preset", "")
            snipped = tc.get("snipped", False)
            tc_url = tc.get("url", "")

            if snipped:
                continue

            actual_url = stream_urls.get(tc_url)
            if not actual_url:
                continue

            is_m3u8 = ".m3u8" in actual_url

            # Determine format info
            ext = "mp3"
            abr = 128
            if "opus" in preset or "opus" in mime:
                ext = "opus"
                abr = 64
            elif "aac" in preset:
                ext = "m4a"
                abr_match = re.search(r"(\d+)k", preset)
                abr = int(abr_match.group(1)) if abr_match else 160

            hls_tag = " (HLS)" if is_m3u8 else ""
            label = f"{ext.upper()} {abr}kbps{hls_tag}"
            quality = f"{abr}kbps"

            variants.append(ScrapedVariant(
                label=label,
                format=ext,
                url=actual_url,
                quality=quality,
                has_video=False,
                has_audio=True,
            ))

        return variants

    async def _extract_track_via_api(
        self, track: dict, client_id: str,
        http: Optional[httpx.AsyncClient] = None,
    ) -> list[ScrapedVariant]:
        """Resolve stream URLs for a single track from API data and build variants."""
        track_auth = track.get("track_authorization", "")
        media = track.get("media", {})
        transcodings = media.get("transcodings", [])

        if not transcodings:
            return []

        # Resolve stream URLs — prefer progressive over HLS
        stream_urls: dict[str, str] = {}
        for tc in transcodings:
            tc_url = tc.get("url", "")
            if not tc_url or tc.get("snipped", False):
                continue
            fmt = tc.get("format", {})
            # Only resolve progressive (direct HTTP) transcodings
            if fmt.get("protocol") != "progressive":
                continue
            actual = await self._api_get_stream_url(tc_url, client_id, track_auth, http)
            if actual and ".m3u8" not in actual:
                stream_urls[tc_url] = actual

        # Fallback: if no progressive transcodings, resolve HLS audio/mpeg
        if not stream_urls:
            for tc in transcodings:
                tc_url = tc.get("url", "")
                if not tc_url or tc.get("snipped", False):
                    continue
                fmt = tc.get("format", {})
                proto = fmt.get("protocol", "")
                mime = fmt.get("mime_type", "")
                # Only non-encrypted HLS with audio/mpeg
                if proto == "hls" and "mpeg" in mime:
                    actual = await self._api_get_stream_url(tc_url, client_id, track_auth, http)
                    if actual:
                        stream_urls[tc_url] = actual
                    break  # one HLS stream is enough

        return self._build_variants_from_track_data(track, stream_urls)

    # ── URL classification ──────────────────────────────────────

    @staticmethod
    def _classify_url(url: str) -> str:
        """Classify a SoundCloud URL into a content type."""
        path = urlparse(url).path.strip("/")
        parts = path.split("/")

        if not parts or not parts[0]:
            return "unknown"

        # soundcloud.com/<user>/sets/<name>
        if len(parts) >= 3 and parts[1] == "sets":
            return "playlist"

        # soundcloud.com/<user>/tracks
        if len(parts) == 2 and parts[1] == "tracks":
            return "user_tracks"

        # soundcloud.com/<user>/likes
        if len(parts) == 2 and parts[1] == "likes":
            return "user_likes"

        # soundcloud.com/<user>/reposts
        if len(parts) == 2 and parts[1] == "reposts":
            return "user_reposts"

        # soundcloud.com/<user>/albums
        if len(parts) == 2 and parts[1] == "albums":
            return "user_albums"

        # soundcloud.com/<user>/<track>
        if len(parts) == 2:
            return "track"

        # soundcloud.com/<user> (profile page)
        if len(parts) == 1:
            return "user_tracks"

        return "track"

    # ── Main entry point ────────────────────────────────────────

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        url_type = self._classify_url(url)
        tab = (content_tab or "").lower().strip()

        # Route to appropriate handler
        if url_type == "playlist":
            return await self._scrape_playlist(url, tab)
        elif url_type in ("user_tracks", "user_likes", "user_reposts", "user_albums"):
            return await self._scrape_user_collection(url, url_type, tab)
        else:
            return await self._scrape_track(url, tab)

    # ── Single track extraction ─────────────────────────────────

    async def _scrape_track(self, url: str, tab: str) -> ScrapedResult:
        """Extract a single track (also handles podcast episodes)."""

        # Strategy 1: SoundCloud API v2 (fresh client_id, most reliable)
        client_id = await self._get_client_id()
        if client_id:
            try:
                data = await self._api_resolve(url, client_id)
                if data and data.get("kind") == "track" and data.get("policy") != "BLOCK":
                    variants = await self._extract_track_via_api(data, client_id)

                    # Add waveform
                    waveform_url = data.get("waveform_url")
                    if waveform_url:
                        variants.append(ScrapedVariant(
                            label="Waveform Image",
                            format="png",
                            url=waveform_url.replace(".json", ".png"),
                            quality="waveform",
                            has_video=False,
                            has_audio=False,
                        ))

                    # Add artwork
                    artwork_url = data.get("artwork_url")
                    if artwork_url:
                        original = re.sub(
                            r"-(mini|tiny|small|badge|t67x67|large|t300x300|crop|t500x500|original)\.",
                            "-original.", artwork_url,
                        )
                        variants.append(ScrapedVariant(
                            label="Cover Art (Original)",
                            format="jpg",
                            url=original,
                            quality="original",
                            has_video=False,
                            has_audio=False,
                        ))
                        t500 = re.sub(
                            r"-(mini|tiny|small|badge|t67x67|large|t300x300|crop|t500x500|original)\.",
                            "-t500x500.", artwork_url,
                        )
                        if t500 != original:
                            variants.append(ScrapedVariant(
                                label="Cover Art (500x500)",
                                format="jpg",
                                url=t500,
                                quality="500x500",
                                has_video=False,
                                has_audio=False,
                            ))

                    has_audio = any(v.has_audio for v in variants)
                    if has_audio:
                        duration_ms = data.get("full_duration") or data.get("duration")
                        content_type = self._detect_content_type_from_api(data, tab)
                        return ScrapedResult(
                            title=data.get("title"),
                            description=data.get("description"),
                            author=(data.get("user") or {}).get("username"),
                            thumbnail_url=artwork_url,
                            duration_seconds=round(duration_ms / 1000) if duration_ms else None,
                            content_type=content_type,
                            variants=variants,
                        )
            except Exception as exc:
                logger.debug("soundcloud_api_track_failed", url=url, error=str(exc)[:200])

        # Strategy 2: yt-dlp (fallback)
        try:
            info = await extract_with_ytdlp(url, extra_opts={
                "noplaylist": True,
                "format": "http_mp3/bestaudio[protocol=https]/bestaudio[protocol=http]/bestaudio",
            })
            variants = await self._build_audio_variants(info)
            waveform_url = self._extract_waveform_url(info)

            if waveform_url:
                variants.append(ScrapedVariant(
                    label="Waveform Image",
                    format="png",
                    url=waveform_url,
                    quality="waveform",
                    has_video=False,
                    has_audio=False,
                ))

            artwork_variants = self._build_artwork_variants(info)
            variants.extend(artwork_variants)

            if variants:
                content_type = self._detect_content_type(info, tab)
                return ScrapedResult(
                    title=info.get("title") or info.get("track"),
                    description=info.get("description"),
                    author=info.get("uploader"),
                    thumbnail_url=info.get("thumbnail"),
                    duration_seconds=info.get("duration"),
                    content_type=content_type,
                    variants=variants,
                )
        except Exception as exc:
            logger.debug("soundcloud_ytdlp_track_failed", url=url, error=str(exc)[:200])

        # Strategy 2: oEmbed API (metadata + player embed)
        try:
            result = await self._scrape_oembed(url, tab)
            if result and result.variants:
                return result
        except Exception as exc:
            logger.debug("soundcloud_oembed_failed", url=url, error=str(exc)[:200])

        # Strategy 3: HTML OG tags
        try:
            result = await self._scrape_html_og(url, tab)
            if result and result.variants:
                return result
        except Exception as exc:
            logger.debug("soundcloud_og_failed", url=url, error=str(exc)[:200])

        raise ValueError(
            "Could not extract SoundCloud content. "
            "The track may be private, geo-restricted, or removed."
        )

    # ── Playlist / Set extraction ───────────────────────────────

    async def _scrape_playlist(self, url: str, tab: str) -> ScrapedResult:
        """Extract all tracks from a playlist/set."""

        # Strategy 1: API v2
        client_id = await self._get_client_id()
        if client_id:
            try:
                data = await self._api_resolve(url, client_id)
                if data and data.get("kind") == "playlist":
                    tracks = data.get("tracks", [])
                    if tracks:
                        return await self._build_playlist_result_from_api(
                            data, tracks, client_id,
                        )
            except Exception as exc:
                logger.debug("soundcloud_api_playlist_failed", error=str(exc)[:200])

        # Strategy 2: yt-dlp fallback
        try:
            info = await extract_with_ytdlp(url, extra_opts={
                "noplaylist": False,
                "format": "http_mp3/bestaudio[protocol=https]/bestaudio[protocol=http]/bestaudio",
            })
        except Exception as exc:
            logger.debug("soundcloud_ytdlp_playlist_failed", error=str(exc)[:200])
            raise ValueError(
                "Could not extract SoundCloud playlist. "
                "It may be private or removed."
            ) from exc

        entries = info.get("entries", [])
        if not entries:
            raise ValueError("Playlist is empty or could not be loaded.")

        all_variants: list[ScrapedVariant] = []
        track_count = 0

        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            track_count += 1
            track_title = entry.get("title", f"Track {i + 1}")
            track_variants = await self._build_audio_variants(entry)

            for v in track_variants:
                v.label = f"[{i + 1}] {track_title} – {v.label}"
                all_variants.append(v)

            waveform = self._extract_waveform_url(entry)
            if waveform:
                all_variants.append(ScrapedVariant(
                    label=f"[{i + 1}] {track_title} – Waveform",
                    format="png",
                    url=waveform,
                    quality="waveform",
                    has_video=False,
                    has_audio=False,
                ))

        if not all_variants:
            raise ValueError("No downloadable tracks in this playlist.")

        total_duration = sum(
            e.get("duration", 0) for e in entries if isinstance(e, dict)
        )

        return ScrapedResult(
            title=info.get("title", "SoundCloud Playlist"),
            description=info.get("description") or f"{track_count} tracks",
            author=info.get("uploader"),
            thumbnail_url=info.get("thumbnail") or (
                entries[0].get("thumbnail") if entries else None
            ),
            duration_seconds=total_duration or None,
            page_count=track_count,
            content_type="playlist",
            variants=all_variants,
        )

    async def _build_playlist_result_from_api(
        self, playlist_data: dict, tracks: list[dict], client_id: str,
    ) -> ScrapedResult:
        """Build ScrapedResult for a playlist from API v2 data."""
        all_variants: list[ScrapedVariant] = []
        track_count = 0

        # Limit to first 50 tracks to avoid timeouts
        tracks = tracks[:50]

        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, headers=_HEADERS,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        ) as http:
            for i, track in enumerate(tracks):
                if not isinstance(track, dict):
                    continue

                # Some tracks in playlists only have basic info (id, no media).
                # Fetch full track data if transcodings are missing.
                if not track.get("media", {}).get("transcodings"):
                    track_id = track.get("id")
                    if track_id:
                        try:
                            resp = await http.get(
                                f"{_SC_API_BASE}/tracks/{track_id}?client_id={client_id}"
                            )
                            if resp.status_code == 200:
                                track = resp.json()
                        except Exception:
                            pass

                if track.get("policy") == "BLOCK":
                    continue

                track_count += 1
                track_title = track.get("title", f"Track {i + 1}")

                try:
                    track_variants = await self._extract_track_via_api(track, client_id, http)
                except Exception:
                    continue

                for v in track_variants:
                    v.label = f"[{i + 1}] {track_title} – {v.label}"
                    all_variants.append(v)

                # Waveform
                waveform_url = track.get("waveform_url")
                if waveform_url:
                    all_variants.append(ScrapedVariant(
                        label=f"[{i + 1}] {track_title} – Waveform",
                        format="png",
                        url=waveform_url.replace(".json", ".png"),
                        quality="waveform",
                        has_video=False,
                        has_audio=False,
                    ))

        if not all_variants:
            raise ValueError("No downloadable tracks in this playlist.")

        total_duration = playlist_data.get("duration", 0)
        artwork = playlist_data.get("artwork_url") or (
            tracks[0].get("artwork_url") if tracks else None
        )

        return ScrapedResult(
            title=playlist_data.get("title", "SoundCloud Playlist"),
            description=playlist_data.get("description") or f"{track_count} tracks",
            author=(playlist_data.get("user") or {}).get("username"),
            thumbnail_url=artwork,
            duration_seconds=round(total_duration / 1000) if total_duration else None,
            page_count=track_count,
            content_type="playlist",
            variants=all_variants,
        )

    # ── User collection (tracks/likes/reposts) ──────────────────

    async def _scrape_user_collection(self, url: str, url_type: str, tab: str) -> ScrapedResult:
        """Extract tracks from a user's profile page."""

        # Strategy 1: API v2
        client_id = await self._get_client_id()
        if client_id:
            try:
                data = await self._api_resolve(url, client_id)
                if data and data.get("kind") == "user":
                    user_id = data.get("id")
                    username = data.get("username", "")
                    # Fetch user's tracks
                    endpoint = "tracks"
                    if "likes" in url_type:
                        endpoint = "likes"
                    elif "reposts" in url_type:
                        endpoint = "reposts"

                    async with httpx.AsyncClient(
                        timeout=15, follow_redirects=True, headers=_HEADERS,
                    ) as http:
                        resp = await http.get(
                            f"{_SC_API_BASE}/users/{user_id}/{endpoint}"
                            f"?client_id={client_id}&limit=50&offset=0"
                        )
                        if resp.status_code == 200:
                            collection = resp.json()
                            items = collection.get("collection", [])
                            # For likes, the track is nested under "track"
                            tracks = []
                            for item in items:
                                if isinstance(item, dict):
                                    t = item.get("track", item)
                                    if isinstance(t, dict) and t.get("kind") == "track":
                                        tracks.append(t)
                            if tracks:
                                result = await self._build_playlist_result_from_api(
                                    {"title": f"{username}'s {url_type.replace('user_', '').title()}",
                                     "description": f"{len(tracks)} tracks",
                                     "user": data, "duration": 0,
                                     "artwork_url": data.get("avatar_url")},
                                    tracks, client_id,
                                )
                                return result
            except Exception as exc:
                logger.debug("soundcloud_api_user_failed", error=str(exc)[:200])

        # Strategy 2: yt-dlp fallback
        try:
            info = await extract_with_ytdlp(url, extra_opts={
                "noplaylist": False,
                "playlistend": 50,
                "format": "http_mp3/bestaudio[protocol=https]/bestaudio[protocol=http]/bestaudio",
            })
        except Exception as exc:
            logger.debug("soundcloud_ytdlp_user_failed", error=str(exc)[:200])
            raise ValueError(
                "Could not extract SoundCloud user content. "
                "The profile may be private or not found."
            ) from exc

        entries = info.get("entries", [])
        if not entries:
            raise ValueError("No tracks found on this profile page.")

        all_variants: list[ScrapedVariant] = []
        track_count = 0

        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            track_count += 1
            track_title = entry.get("title", f"Track {i + 1}")
            track_variants = await self._build_audio_variants(entry)

            for v in track_variants:
                v.label = f"[{i + 1}] {track_title} – {v.label}"
                all_variants.append(v)

        if not all_variants:
            raise ValueError("No downloadable tracks found.")

        total_duration = sum(
            e.get("duration", 0) for e in entries if isinstance(e, dict)
        )

        type_label = url_type.replace("user_", "").title()
        return ScrapedResult(
            title=info.get("title") or f"SoundCloud {type_label}",
            description=f"{track_count} tracks",
            author=info.get("uploader"),
            thumbnail_url=info.get("thumbnail") or (
                entries[0].get("thumbnail") if entries else None
            ),
            duration_seconds=total_duration or None,
            page_count=track_count,
            content_type="playlist",
            variants=all_variants,
        )

    # ── Audio variant builder ───────────────────────────────────

    async def _build_audio_variants(self, info: dict) -> list[ScrapedVariant]:
        """Build download variants from yt-dlp format info."""
        variants: list[ScrapedVariant] = []
        seen_formats: set[str] = set()

        for fmt in info.get("formats", []):
            dl_url = fmt.get("url")
            if not dl_url:
                continue

            ext = fmt.get("ext", "mp3")
            format_id = fmt.get("format_id", "")
            protocol = fmt.get("protocol", "")
            abr = fmt.get("abr")

            # Skip HLS/DASH manifests (not directly downloadable)
            if protocol in ("m3u8_native", "m3u8"):
                continue

            # De-duplicate formats
            dedup_key = f"{ext}_{abr}"
            if dedup_key in seen_formats:
                continue
            seen_formats.add(dedup_key)

            # Build human-readable label
            label = self._format_label(ext, abr, format_id)

            variants.append(ScrapedVariant(
                label=label,
                format=ext,
                url=dl_url,
                quality=f"{abr}kbps" if abr else None,
                file_size_bytes=fmt.get("filesize") or fmt.get("filesize_approx"),
                has_video=False,
                has_audio=True,
            ))

        # Fallback: top-level URL from info dict (only if direct HTTP)
        if not variants and info.get("url"):
            protocol = info.get("protocol", "")
            top_url = info["url"]
            if protocol not in ("m3u8_native", "m3u8") and ".m3u8" not in top_url:
                variants.append(ScrapedVariant(
                    label=f"Audio ({info.get('ext', 'mp3').upper()})",
                    format=info.get("ext", "mp3"),
                    url=top_url,
                    quality=f"{info.get('abr')}kbps" if info.get("abr") else None,
                    file_size_bytes=info.get("filesize") or info.get("filesize_approx"),
                    has_video=False,
                    has_audio=True,
                ))

        # Last resort: resolve actual segment URL from HLS manifest
        if not variants:
            for fmt in info.get("formats", []):
                dl_url = fmt.get("url")
                if not dl_url:
                    continue
                # Try to resolve HLS to a direct segment URL
                resolved = await self._resolve_hls_to_direct(dl_url)
                if resolved:
                    ext = fmt.get("ext", "mp3")
                    abr = fmt.get("abr")
                    label = self._format_label(ext, abr, fmt.get("format_id", ""))
                    variants.append(ScrapedVariant(
                        label=label,
                        format=ext,
                        url=resolved,
                        quality=f"{abr}kbps" if abr else None,
                        file_size_bytes=fmt.get("filesize") or fmt.get("filesize_approx"),
                        has_video=False,
                        has_audio=True,
                    ))
                    break

        return variants

    @staticmethod
    def _format_label(ext: str, abr: Optional[float], format_id: str) -> str:
        """Build a user-friendly label for an audio format."""
        ext_upper = ext.upper()
        if abr:
            return f"{ext_upper} {int(abr)}kbps"
        if "mp3" in format_id:
            return "MP3 128kbps"
        if "opus" in format_id:
            return "OPUS 64kbps"
        if "aac" in format_id:
            return "AAC 160kbps"
        return f"Audio ({ext_upper})"

    # ── HLS resolution ──────────────────────────────────────────

    @staticmethod
    async def _resolve_hls_to_direct(m3u8_url: str) -> Optional[str]:
        """
        Fetch an HLS m3u8 playlist and extract the direct media segment URL.

        SoundCloud HLS playlists typically contain a single segment that is
        the full audio file.  We parse the playlist, find the first media
        segment URL, and return it for direct download.
        """
        try:
            async with httpx.AsyncClient(
                timeout=10, follow_redirects=True, headers=_HEADERS,
            ) as client:
                resp = await client.get(m3u8_url)
                resp.raise_for_status()
                content = resp.text

            # Parse m3u8: find lines that are URLs (not comments)
            base_url = m3u8_url.rsplit("/", 1)[0] + "/"
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # This is a media segment URL
                if line.startswith("http"):
                    return line
                else:
                    # Relative URL
                    return base_url + line
        except Exception as exc:
            logger.debug("soundcloud_hls_resolve_failed", error=str(exc)[:200])
        return None

    # ── Waveform extraction ─────────────────────────────────────

    @staticmethod
    def _extract_waveform_url(info: dict) -> Optional[str]:
        """
        Extract the waveform PNG URL from SoundCloud metadata.

        SoundCloud stores waveforms as JSON at sndcdn.com/…/waveform.json
        but also provides visual waveform images via the artwork system.
        The waveform_url from the API returns a JSON with sample data;
        we construct a visual PNG waveform URL from the track ID.
        """
        # yt-dlp sometimes provides waveform_url in the info dict
        waveform_url = info.get("waveform_url")
        if waveform_url:
            # Convert JSON waveform URL to PNG
            # w1.sndcdn.com/…/waveform.json → wave1.sndcdn.com/…/waveform.png
            png_url = waveform_url.replace(".json", ".png")
            return png_url

        # Build from track ID if available
        track_id = info.get("id") or info.get("display_id")
        if track_id:
            return f"https://wave1.sndcdn.com/{track_id}_m.png"

        return None

    # ── Artwork variants ────────────────────────────────────────

    @staticmethod
    def _build_artwork_variants(info: dict) -> list[ScrapedVariant]:
        """Extract high-quality artwork/cover images."""
        variants: list[ScrapedVariant] = []

        # Use the thumbnail URL and generate size variants
        thumbnail = info.get("thumbnail")
        if not thumbnail:
            thumbnails = info.get("thumbnails", [])
            for t in reversed(thumbnails):
                if t.get("url"):
                    thumbnail = t["url"]
                    break

        if thumbnail:
            # SoundCloud artwork sizes: mini, tiny, small, badge, t67x67,
            # large, t300x300, crop, t500x500, original
            # Replace any size identifier with "original" for highest quality
            original_url = re.sub(
                r"-(mini|tiny|small|badge|t67x67|large|t300x300|crop|t500x500|original)\.",
                "-original.",
                thumbnail,
            )
            variants.append(ScrapedVariant(
                label="Cover Art (Original)",
                format="jpg",
                url=original_url,
                quality="original",
                has_video=False,
                has_audio=False,
            ))

            # Also add a 500x500 version
            t500_url = re.sub(
                r"-(mini|tiny|small|badge|t67x67|large|t300x300|crop|t500x500|original)\.",
                "-t500x500.",
                thumbnail,
            )
            if t500_url != original_url:
                variants.append(ScrapedVariant(
                    label="Cover Art (500x500)",
                    format="jpg",
                    url=t500_url,
                    quality="500x500",
                    has_video=False,
                    has_audio=False,
                ))

        return variants

    # ── Content type detection ──────────────────────────────────

    @staticmethod
    def _detect_content_type(info: dict, tab: str) -> str:
        """Determine the content type based on metadata and user tab selection."""
        if tab in ("podcasts", "podcast"):
            return "podcast"
        if tab in ("waveforms", "waveform"):
            return "audio"

        # Check genre/tags for podcast indicators
        genre = (info.get("genre") or "").lower()
        tags = [t.lower() for t in (info.get("tags") or [])]
        podcast_keywords = {"podcast", "episode", "talk", "interview", "spoken word"}
        if genre in podcast_keywords or any(t in podcast_keywords for t in tags):
            return "podcast"

        return "audio"

    @staticmethod
    def _detect_content_type_from_api(data: dict, tab: str) -> str:
        """Content type detection for API v2 track data."""
        if tab in ("podcasts", "podcast"):
            return "podcast"
        if tab in ("waveforms", "waveform"):
            return "audio"

        genre = (data.get("genre") or "").lower()
        tag_list = (data.get("tag_list") or "").lower()
        podcast_keywords = {"podcast", "episode", "talk", "interview", "spoken word"}
        if genre in podcast_keywords or any(k in tag_list for k in podcast_keywords):
            return "podcast"

        return "audio"

    # ── oEmbed fallback ─────────────────────────────────────────

    async def _scrape_oembed(self, url: str, tab: str) -> Optional[ScrapedResult]:
        """Use SoundCloud's oEmbed API for basic metadata."""
        oembed_url = f"https://soundcloud.com/oembed?format=json&url={quote(url, safe='')}"

        async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as client:
            resp = await client.get(oembed_url)
            resp.raise_for_status()
            data = resp.json()

        title = data.get("title")
        author = data.get("author_name")
        thumbnail = data.get("thumbnail_url")

        variants: list[ScrapedVariant] = []
        if thumbnail:
            # Get original-quality artwork
            original_url = re.sub(
                r"-(mini|tiny|small|badge|t67x67|large|t300x300|crop|t500x500|original)\.",
                "-original.",
                thumbnail,
            )
            variants.append(ScrapedVariant(
                label="Cover Art (Original)",
                format="jpg",
                url=original_url,
                quality="original",
                has_video=False,
                has_audio=False,
            ))

        # Extract track ID from the embed HTML if present
        html = data.get("html", "")
        track_id_match = re.search(r"tracks/(\d+)", html)
        if track_id_match:
            track_id = track_id_match.group(1)
            # Waveform image
            variants.append(ScrapedVariant(
                label="Waveform Image",
                format="png",
                url=f"https://wave1.sndcdn.com/{track_id}_m.png",
                quality="waveform",
                has_video=False,
                has_audio=False,
            ))

        if not variants:
            return None

        return ScrapedResult(
            title=title or "SoundCloud Track",
            description=data.get("description"),
            author=author,
            thumbnail_url=thumbnail,
            content_type="audio",
            variants=variants,
        )

    # ── HTML OG-tag fallback ────────────────────────────────────

    async def _scrape_html_og(self, url: str, tab: str) -> Optional[ScrapedResult]:
        """Parse OG tags from the HTML page as last resort."""
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={**_HEADERS, "Accept": "text/html"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        if len(html) < 500:
            return None

        og_title = find_og_tag(html, "og:title")
        og_desc = find_og_tag(html, "og:description")
        og_image = find_og_tag(html, "og:image")
        og_audio = find_og_tag(html, "og:audio")
        og_type = find_og_tag(html, "og:type")

        variants: list[ScrapedVariant] = []

        if og_audio:
            variants.append(ScrapedVariant(
                label="Audio Stream",
                format="mp3",
                url=og_audio,
                has_video=False,
                has_audio=True,
            ))

        if og_image:
            original_url = re.sub(
                r"-(mini|tiny|small|badge|t67x67|large|t300x300|crop|t500x500|original)\.",
                "-original.",
                og_image,
            )
            variants.append(ScrapedVariant(
                label="Cover Art",
                format="jpg",
                url=original_url,
                has_video=False,
                has_audio=False,
            ))

        if not variants:
            return None

        content_type = "playlist" if og_type and "playlist" in og_type else "audio"

        return ScrapedResult(
            title=og_title or "SoundCloud Content",
            description=og_desc,
            thumbnail_url=og_image,
            content_type=content_type,
            variants=variants,
        )
