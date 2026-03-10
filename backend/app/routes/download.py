"""
Download proxy route.

GET /api/download?url=<encoded_url>&filename=<optional>

Fetches the remote file server-side (bypasses CORS / origin restrictions)
and streams it to the client with Content-Disposition: attachment so the
browser triggers a real file-save dialog.
"""

import asyncio
import os
import re
import tempfile

import httpx
import structlog
from urllib.parse import unquote, urlparse, quote
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

logger = structlog.get_logger()

router = APIRouter(prefix="/api", tags=["download"])

# Allowed URL hosts to prevent open-redirect / SSRF abuse
_ALLOWED_HOSTS_RE = re.compile(
    r"(googlevideo\.com|youtube\.com|ytimg\.com|"
    r"instagram\.com|fbcdn\.net|cdninstagram\.com|facebook\.com|"
    r"tiktokcdn\.com|tiktokv\.com|musical\.ly|"
    r"scdn\.co|soundcloud\.com|sndcdn\.com|media-streaming\.soundcloud\.cloud|"
    r"twimg\.com|pbs\.twimg\.com|video\.twimg\.com|"
    r"fxtwitter\.com|"
    r"snapchat\.com|sc-cdn\.net|"
    r"vimeo\.com|vimeocdn\.com|"
    r"reddit\.com|redd\.it|redditmedia\.com|redgifs\.com|"
    r"tumblr\.com|pinimg\.com|"
    r"media\.licdn\.com|linkedin\.com|"
    r"threads\.net|threads\.com|"
    r"scribd\.com|html\.scribd\.com|imgv2[^.]*\.scribd\.com|"
    r"slidesharecdn\.com|image\.slidesharecdn\.com|cdn\.slidesharecdn\.com|"
    r"slideserve\.com|cdn\d*\.slideserve\.com|image\d*\.slideserve\.com|"
    r"calameoassets\.com|ps\.calameoassets\.com|i\.calameoassets\.com|"
    r"yumpu\.com|img\.yumpu\.com|assets\.yumpu\.com|image\.yumpu\.com|"
    r"documents-public\.yumpu\.news|documents\.yumpu\.news|assets\.yumpu\.news|"
    r"scontent|rr[0-9]---|"
    r"akamaized\.net|cloudfront\.net|cdn\.)",
    re.IGNORECASE,
)

# Map of common extensions to MIME types for the Content-Type header
_MIME_MAP = {
    "mp4": "video/mp4",
    "webm": "video/webm",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "wav": "audio/wav",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _build_source_headers(decoded_url: str) -> dict[str, str]:
    """Build source-aware headers so CDNs accept proxied requests."""
    host = (urlparse(decoded_url).netloc or "").lower()

    referer = "https://www.youtube.com/"
    origin = "https://www.youtube.com"

    if any(domain in host for domain in ("instagram.com", "cdninstagram.com", "fbcdn.net", "scontent")):
        referer = "https://www.instagram.com/"
        origin = "https://www.instagram.com"
    elif any(domain in host for domain in ("facebook.com", "fbcdn.net")):
        referer = "https://www.facebook.com/"
        origin = "https://www.facebook.com"
    elif any(domain in host for domain in ("tiktok.com", "tiktokcdn.com", "tiktokv.com", "musical.ly")):
        referer = "https://www.tiktok.com/"
        origin = "https://www.tiktok.com"
    elif any(domain in host for domain in ("x.com", "twitter.com", "twimg.com")):
        referer = "https://x.com/"
        origin = "https://x.com"
    elif any(domain in host for domain in ("snapchat.com", "sc-cdn.net")):
        referer = "https://www.snapchat.com/"
        origin = "https://www.snapchat.com"
    elif any(domain in host for domain in ("linkedin.com", "licdn.com")):
        referer = "https://www.linkedin.com/"
        origin = "https://www.linkedin.com"
    elif "pinimg.com" in host:
        referer = "https://www.pinterest.com/"
        origin = "https://www.pinterest.com"
    elif any(domain in host for domain in ("reddit.com", "redd.it", "redditmedia.com")):
        referer = "https://www.reddit.com/"
        origin = "https://www.reddit.com"
    elif any(domain in host for domain in ("threads.net", "threads.com")):
        referer = "https://www.threads.net/"
        origin = "https://www.threads.net"
    elif "scribd.com" in host:
        referer = "https://www.scribd.com/"
        origin = "https://www.scribd.com"
    elif any(domain in host for domain in ("soundcloud.com", "sndcdn.com", "scdn.co", "media-streaming.soundcloud.cloud")):
        referer = "https://soundcloud.com/"
        origin = "https://soundcloud.com"
    elif "slidesharecdn.com" in host:
        referer = "https://www.slideshare.net/"
        origin = "https://www.slideshare.net"
    elif "slideserve.com" in host:
        referer = "https://www.slideserve.com/"
        origin = "https://www.slideserve.com"
    elif "calameoassets.com" in host:
        referer = "https://www.calameo.com/"
        origin = "https://www.calameo.com"
    elif "yumpu.com" in host or "yumpu.news" in host:
        referer = "https://www.yumpu.com/"
        origin = "https://www.yumpu.com"

    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": referer,
        "Origin": origin,
        "Accept": "*/*",
    }


async def _download_hls(decoded_url: str, filename: str) -> StreamingResponse:
    """
    Download an HLS m3u8 playlist by fetching all segments and
    streaming them concatenated as a single MP3 file.
    """
    safe_filename = re.sub(r'[^\w \-.]', '', filename.replace('\n', ' ').replace('\r', ''))[:100].strip() or "download"

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=60.0, headers=_build_source_headers(decoded_url),
    ) as client:
        # Fetch the m3u8 playlist
        resp = await client.get(decoded_url)
        if resp.status_code != 200:
            raise HTTPException(502, f"Failed to fetch HLS playlist: {resp.status_code}")

        # Parse segment URLs from the m3u8
        segment_urls: list[str] = []
        for line in resp.text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                segment_urls.append(line)

        if not segment_urls:
            raise HTTPException(502, "HLS playlist contained no segments")

        logger.info("hls_download_start", segments=len(segment_urls), url=decoded_url[:80])

    # Determine extension from the first segment URL
    ext = "mp3"
    first_path = urlparse(segment_urls[0]).path.lower()
    for candidate_ext in _MIME_MAP:
        if f".{candidate_ext}" in first_path:
            ext = candidate_ext
            break

    mime = _MIME_MAP.get(ext, "application/octet-stream")
    full_filename = f"{safe_filename}.{ext}"

    headers = {
        "Content-Disposition": f'attachment; filename="{full_filename}"',
        "Content-Type": mime,
        "Access-Control-Expose-Headers": "Content-Disposition",
    }

    async def stream_segments():
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=60.0,
            headers=_build_source_headers(decoded_url),
        ) as client:
            for seg_url in segment_urls:
                try:
                    seg_resp = await client.get(seg_url)
                    if seg_resp.status_code == 200:
                        yield seg_resp.content
                except Exception:
                    continue  # skip failed segments

    return StreamingResponse(
        stream_segments(),
        headers=headers,
        media_type=mime,
    )


@router.get("/download")
async def proxy_download(
    url: str = Query(..., description="The remote file URL to download"),
    filename: str = Query("download", description="Suggested filename (without extension)"),
):
    """Stream a remote media file through the backend so the browser can save it."""

    decoded_url = unquote(url)

    # Basic SSRF protection: only allow known CDN hosts
    if not _ALLOWED_HOSTS_RE.search(decoded_url):
        raise HTTPException(
            403,
            "URL host is not in the allow-list. Only supported platform CDN URLs are permitted.",
        )

    # ── HLS / m3u8 handling ─────────────────────────────────────
    # If the URL is an m3u8 playlist, fetch all segments and stream them
    # concatenated as a single file (e.g. MP3).
    if ".m3u8" in decoded_url or "playlist.m3u8" in decoded_url:
        return await _download_hls(decoded_url, filename)

    client = httpx.AsyncClient(follow_redirects=True, timeout=300.0)

    try:
        req = client.build_request("GET", decoded_url, headers=_build_source_headers(decoded_url))
        resp = await client.send(req, stream=True)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        await client.aclose()
        logger.error("download_proxy_http_error", status=exc.response.status_code, url=decoded_url[:120])
        raise HTTPException(502, f"Remote server returned {exc.response.status_code}")
    except httpx.RequestError as exc:
        await client.aclose()
        logger.error("download_proxy_request_error", error=str(exc)[:200])
        raise HTTPException(502, "Failed to fetch the remote file")

    # Determine content type and extension
    remote_ct = resp.headers.get("content-type", "application/octet-stream")
    ext = "bin"  # generic default instead of mp4
    for candidate_ext, mime in _MIME_MAP.items():
        if mime in remote_ct:
            ext = candidate_ext
            break
    # Also check URL extension as fallback if MIME was unknown
    if ext == "bin":
        url_path = urlparse(decoded_url).path.lower()
        for candidate_ext in _MIME_MAP:
            if url_path.endswith(f".{candidate_ext}"):
                ext = candidate_ext
                break

    safe_filename = re.sub(r'[^\w \-.]', '', filename.replace('\n', ' ').replace('\r', ''))[:100].strip() or "download"
    full_filename = f"{safe_filename}.{ext}"

    headers = {
        "Content-Disposition": f'attachment; filename="{full_filename}"',
        "Content-Type": remote_ct,
        "Access-Control-Expose-Headers": "Content-Disposition",
    }
    content_length = resp.headers.get("content-length")
    if content_length:
        headers["Content-Length"] = content_length

    async def stream_content():
        try:
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        stream_content(),
        headers=headers,
        media_type=remote_ct,
    )


@router.get("/stream")
async def proxy_stream(
    url: str = Query(..., description="The remote media URL to stream for inline playback"),
):
    """Stream a remote media file for inline playback (video/audio preview in the browser)."""

    decoded_url = unquote(url)

    if not _ALLOWED_HOSTS_RE.search(decoded_url):
        raise HTTPException(
            403,
            "URL host is not in the allow-list. Only supported platform CDN URLs are permitted.",
        )

    client = httpx.AsyncClient(follow_redirects=True, timeout=300.0)

    try:
        req = client.build_request("GET", decoded_url, headers=_build_source_headers(decoded_url))
        resp = await client.send(req, stream=True)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        await client.aclose()
        logger.error("stream_proxy_http_error", status=exc.response.status_code, url=decoded_url[:120])
        raise HTTPException(502, f"Remote server returned {exc.response.status_code}")
    except httpx.RequestError as exc:
        await client.aclose()
        logger.error("stream_proxy_request_error", error=str(exc)[:200])
        raise HTTPException(502, "Failed to fetch the remote file")

    remote_ct = resp.headers.get("content-type", "application/octet-stream")

    headers = {
        "Content-Type": remote_ct,
        "Cache-Control": "public, max-age=300",
    }
    content_length = resp.headers.get("content-length")
    if content_length:
        headers["Content-Length"] = content_length

    async def stream_content():
        try:
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        stream_content(),
        headers=headers,
        media_type=remote_ct,
    )


# ── Merge multiple video segments into one file ─────────────────

def _get_ffmpeg_path() -> str:
    """Return the path to the ffmpeg binary (bundled via imageio-ffmpeg)."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise HTTPException(500, "ffmpeg not available on the server")


@router.get("/download/merge")
async def merge_download(
    urls: str = Query(..., description="Pipe-separated list of remote media URLs"),
    filename: str = Query("download", description="Suggested filename (without extension)"),
):
    """
    Download multiple video/image segments, concatenate them with ffmpeg,
    and stream the merged MP4 back to the client.
    """
    url_list = [u.strip() for u in urls.split("|") if u.strip()]
    if not url_list:
        raise HTTPException(400, "No URLs provided")
    if len(url_list) > 200:
        raise HTTPException(400, "Too many segments (max 200)")

    # Validate all URLs against the allow-list
    for u in url_list:
        decoded = unquote(u)
        if not _ALLOWED_HOSTS_RE.search(decoded):
            raise HTTPException(403, "One or more URLs are not in the allow-list")

    ffmpeg = _get_ffmpeg_path()
    tmp_dir = tempfile.mkdtemp(prefix="merge_")

    try:
        # Download all segments in parallel (limited concurrency)
        sem = asyncio.Semaphore(6)

        async def download_segment(idx: int, u: str) -> str:
            decoded = unquote(u)
            ext = "mp4"
            url_path = urlparse(decoded).path.lower()
            if url_path.endswith(".jpg") or url_path.endswith(".jpeg"):
                ext = "jpg"
            elif url_path.endswith(".png"):
                ext = "png"
            seg_path = os.path.join(tmp_dir, f"seg_{idx:04d}.{ext}")
            async with sem:
                async with httpx.AsyncClient(
                    follow_redirects=True, timeout=60.0,
                    headers=_build_source_headers(decoded),
                ) as client:
                    resp = await client.get(decoded)
                    resp.raise_for_status()
                    with open(seg_path, "wb") as f:
                        f.write(resp.content)
            return seg_path

        tasks = [download_segment(i, u) for i, u in enumerate(url_list)]
        segment_paths = await asyncio.gather(*tasks)

        # Convert images to short videos so they can be concatenated
        converted_paths: list[str] = []
        for seg_path in segment_paths:
            if seg_path.endswith(".mp4"):
                converted_paths.append(seg_path)
            else:
                # Convert image to a 3-second video clip
                img_vid = seg_path.rsplit(".", 1)[0] + "_conv.mp4"
                proc = await asyncio.create_subprocess_exec(
                    ffmpeg, "-loop", "1", "-i", seg_path,
                    "-c:v", "libx264", "-t", "3", "-pix_fmt", "yuv420p",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-y", img_vid,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                if proc.returncode == 0 and os.path.exists(img_vid):
                    converted_paths.append(img_vid)
                else:
                    converted_paths.append(seg_path)

        # Build ffmpeg concat file list
        concat_list = os.path.join(tmp_dir, "concat.txt")
        with open(concat_list, "w") as f:
            for p in converted_paths:
                safe = p.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe}'\n")

        # Run ffmpeg concat
        output_path = os.path.join(tmp_dir, "merged.mp4")
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-f", "concat", "-safe", "0", "-i", concat_list,
            "-c", "copy", "-movflags", "+faststart", "-y", output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            # If copy fails (different codecs), try re-encoding
            logger.warning("merge_copy_failed", stderr=stderr.decode()[:200])
            proc = await asyncio.create_subprocess_exec(
                ffmpeg, "-f", "concat", "-safe", "0", "-i", concat_list,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", "-y", output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise HTTPException(500, f"Failed to merge videos: {stderr.decode()[:200]}")

        if not os.path.exists(output_path):
            raise HTTPException(500, "Merge produced no output")

        file_size = os.path.getsize(output_path)
        safe_filename = re.sub(r'[^\w \-.]', '', filename.replace('\n', ' ').replace('\r', ''))[:100].strip() or "download"
        full_filename = f"{safe_filename}.mp4"

        resp_headers = {
            "Content-Disposition": f'attachment; filename="{full_filename}"',
            "Content-Type": "video/mp4",
            "Content-Length": str(file_size),
            "Access-Control-Expose-Headers": "Content-Disposition",
        }

        async def stream_and_cleanup():
            try:
                with open(output_path, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        yield chunk
            finally:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)

        return StreamingResponse(
            stream_and_cleanup(),
            headers=resp_headers,
            media_type="video/mp4",
        )
    except HTTPException:
        raise
    except Exception as e:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.error("merge_download_error", error=str(e)[:200])
        raise HTTPException(500, f"Failed to merge: {str(e)[:200]}")
