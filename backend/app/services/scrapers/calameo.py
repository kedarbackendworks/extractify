"""
Calameo scraper – extracts publications and documents as PDFs.

Strategy:
  1. Call ``d.calameo.com/pinwheel/viewer/book/get`` via curl subprocess
     (calameo.com blocks Python httpx via TLS fingerprinting; curl bypasses it)
  2. Parse the JSON response → title, key (CDN hash), page count
  3. Extract wildcard signing token from response headers:
     ``X-Calameo-Hash-Path``, ``X-Calameo-Hash-Signature``, ``X-Calameo-Hash-Expires``
  4. Construct signed URLs for every page:
     ``https://ps.calameoassets.com/{key}/p{N}.jpg?_token_=exp=…~acl=…~hmac=…``
  5. Download all page images concurrently via httpx (CDN accepts httpx fine)
  6. Assemble into a single PDF via ``img2pdf``
  7. Serve through ``/api/files/{name}``

Supported URL patterns:
  - https://www.calameo.com/books/CODE
  - https://www.calameo.com/USERNAME/books/CODE
  - https://www.calameo.com/USERNAME/read/CODE
  - https://www.calameo.com/read/CODE
"""

from __future__ import annotations

import asyncio
import io
import json
import platform
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import httpx
import img2pdf
import structlog
from PIL import Image

from app.services.scrapers.base import BaseScraper, ScrapedResult, ScrapedVariant

logger = structlog.get_logger()

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Re-use the same temp directory as Scribd / SlideShare
PDF_DIR = Path(tempfile.gettempdir()) / "extractify_pdfs"
PDF_DIR.mkdir(parents=True, exist_ok=True)

_MAX_PAGES = 500

# Calameo viewer webservice endpoint
_API_URL = "https://d.calameo.com/pinwheel/viewer/book/get"
_BUILD_ID = "9477-000182"

# Signed-image CDN base
_CDN_BASE = "https://ps.calameoassets.com"

# Thumbnail CDN base (unsigned, low-res ~100×141)
_THUMB_CDN = "https://i.calameoassets.com"

# Regex to extract book code from URL
_BOOK_CODE_RE = re.compile(
    r"calameo\.com/(?:[^/]+/)?(?:books|read)/([0-9a-f]{10,})",
    re.IGNORECASE,
)


def _find_curl() -> str:
    """Find the curl binary. Returns 'curl.exe' on Windows, 'curl' elsewhere."""
    if platform.system() == "Windows":
        # Windows ships curl.exe in System32
        return shutil.which("curl.exe") or shutil.which("curl") or "curl.exe"
    return shutil.which("curl") or "curl"


class CalameoScraper(BaseScraper):
    platform = "calameo"

    _DOMAIN_RE = re.compile(r"calameo\.com", re.IGNORECASE)

    def supports(self, url: str) -> bool:
        return bool(self._DOMAIN_RE.search(url))

    # ──────────────────────────────────────────────────────────────
    #  Entry point
    # ──────────────────────────────────────────────────────────────

    async def scrape(self, url: str, content_tab: Optional[str] = None) -> ScrapedResult:
        bkcode = self._extract_book_code(url)
        if not bkcode:
            raise ValueError(
                "Could not extract a book code from the Calameo URL. "
                "Expected format: calameo.com/books/CODE or calameo.com/read/CODE"
            )

        # ── 1. Fetch book data + signing token via API ───────────
        api_data, token_parts = await self._fetch_book_api(bkcode)

        content = api_data.get("content", {})
        title = content.get("name") or "Calameo Document"
        key = content.get("key") or ""
        doc_info = content.get("document", {})
        page_count = doc_info.get("pages") or 0
        doc_width = doc_info.get("width") or 0
        doc_height = doc_info.get("height") or 0

        # Account / author info
        account = content.get("account", {})
        author = account.get("name") or None

        # Thumbnail from the API
        urls_info = content.get("url", {})
        thumbnail = urls_info.get("poster") or urls_info.get("image") or None
        if thumbnail and thumbnail.startswith("//"):
            thumbnail = "https:" + thumbnail

        variants: list[ScrapedVariant] = []

        # ── 2. Build PDF from signed page images ─────────────────
        if key and page_count and token_parts:
            effective_pages = min(page_count, _MAX_PAGES)
            pdf_path = await self._build_pdf(
                bkcode, key, effective_pages, token_parts
            )
            if pdf_path:
                fname = pdf_path.name
                variants.append(ScrapedVariant(
                    label=f"Full Document ({effective_pages} pages)",
                    format="pdf",
                    url=f"/api/files/{fname}",
                    file_size_bytes=pdf_path.stat().st_size,
                ))

        # ── 3. Thumbnail fallback ─────────────────────────────────
        if thumbnail and thumbnail.startswith("http"):
            variants.append(ScrapedVariant(
                label="Thumbnail",
                format="jpg",
                url=thumbnail,
            ))

        if not variants:
            raise ValueError(
                "Could not extract downloadable content from this Calameo publication. "
                "The document may be private or restricted."
            )

        return ScrapedResult(
            title=title,
            author=author,
            thumbnail_url=thumbnail,
            page_count=page_count or None,
            content_type="document",
            variants=variants,
        )

    # ──────────────────────────────────────────────────────────────
    #  API call via curl (bypasses TLS fingerprint blocking)
    # ──────────────────────────────────────────────────────────────

    async def _fetch_book_api(
        self, bkcode: str
    ) -> tuple[dict, Optional[dict]]:
        """
        POST to d.calameo.com viewer API via curl subprocess.

        Returns (json_body, token_parts) where token_parts is:
          {"exp": str, "acl": str, "hmac": str}  or  None
        """
        curl = _find_curl()

        # Build curl command to get both headers and body
        cmd = [
            curl,
            "-s",                       # silent
            "-L",                       # follow redirects
            "-D", "-",                  # dump headers to stdout
            "-X", "POST",
            _API_URL,
            "-H", f"X-Calameo-Build-ID: {_BUILD_ID}",
            "-H", "X-Calameo-Timestamp: 1",
            "-H", "X-Calameo-Expires: 300",
            "-H", "X-Calameo-Delay: 0",
            "-H", f"User-Agent: {_UA}",
            "-d", f"bkcode={bkcode}",
        ]

        logger.info("calameo_api_call", bkcode=bkcode)

        def _run_curl() -> tuple[bytes, bytes, int]:
            """Run curl synchronously (called via asyncio.to_thread)."""
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
            )
            return result.stdout, result.stderr, result.returncode

        try:
            stdout, stderr, returncode = await asyncio.to_thread(_run_curl)
        except subprocess.TimeoutExpired:
            logger.error("calameo_api_timeout", bkcode=bkcode)
            raise ValueError("Calameo API request timed out.")
        except FileNotFoundError:
            logger.error("calameo_curl_not_found")
            raise ValueError(
                "curl is not available on this system. "
                "Please install curl to use the Calameo scraper."
            )
        except Exception as exc:
            import traceback
            logger.error("calameo_subprocess_error",
                         exc_type=type(exc).__name__,
                         exc_msg=str(exc)[:300],
                         tb=traceback.format_exc()[:500])
            raise ValueError(
                f"Failed to call Calameo API: {type(exc).__name__}: {exc}"
            )

        if returncode != 0:
            logger.error("calameo_curl_error",
                         code=returncode,
                         stderr=stderr.decode(errors="replace")[:200])
            raise ValueError("Failed to fetch Calameo book data.")

        raw = stdout.decode(errors="replace")

        # Split headers from body (headers dumped with -D -)
        # curl outputs headers first, then \r\n\r\n, then body
        parts = raw.split("\r\n\r\n", 1)
        if len(parts) < 2:
            # Try with just \n\n
            parts = raw.split("\n\n", 1)

        if len(parts) < 2:
            logger.error("calameo_api_no_body", raw_len=len(raw))
            raise ValueError("Could not parse Calameo API response.")

        headers_raw = parts[0]
        body = parts[1]

        # Parse signing token from headers
        token_parts = self._extract_token_from_headers(headers_raw)

        # Parse JSON body
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            # Sometimes there are multiple header blocks (redirects)
            # Try to find JSON in the remaining content
            json_start = body.find("{")
            if json_start >= 0:
                try:
                    data = json.loads(body[json_start:])
                except json.JSONDecodeError:
                    logger.error("calameo_api_json_fail",
                                 body_preview=body[:200])
                    raise ValueError("Could not parse Calameo API response JSON.")
            else:
                raise ValueError("No JSON found in Calameo API response.")

        if data.get("status") != "ok":
            err_content = data.get("content", {})
            err_msg = err_content.get("msg", "") if isinstance(err_content, dict) else ""
            logger.error("calameo_api_error", status=data.get("status"),
                         error=err_msg)
            raise ValueError(
                f"Calameo API returned error: {err_msg or 'unknown'}"
            )

        logger.info("calameo_api_ok",
                     bkcode=bkcode,
                     title=str(data.get("content", {}).get("name", ""))[:60],
                     pages=data.get("content", {}).get("document", {}).get("pages"),
                     has_token=token_parts is not None)

        return data, token_parts

    @staticmethod
    def _extract_token_from_headers(headers_raw: str) -> Optional[dict]:
        """
        Extract signing token from curl response headers.

        Looks for:
          X-Calameo-Hash-Path: %2F...%2F%2A
          X-Calameo-Hash-Signature: hex_string
          X-Calameo-Hash-Expires: unix_timestamp
        """
        path_m = re.search(
            r"X-Calameo-Hash-Path:\s*(.+)", headers_raw, re.IGNORECASE
        )
        sig_m = re.search(
            r"X-Calameo-Hash-Signature:\s*(\S+)", headers_raw, re.IGNORECASE
        )
        exp_m = re.search(
            r"X-Calameo-Hash-Expires:\s*(\d+)", headers_raw, re.IGNORECASE
        )

        if not (path_m and sig_m and exp_m):
            return None

        return {
            "acl": path_m.group(1).strip(),
            "hmac": sig_m.group(1).strip(),
            "exp": exp_m.group(1).strip(),
        }

    # ──────────────────────────────────────────────────────────────
    #  PDF assembly
    # ──────────────────────────────────────────────────────────────

    async def _build_pdf(
        self,
        bkcode: str,
        key: str,
        page_count: int,
        token_parts: dict,
    ) -> Optional[Path]:
        """Download all page images from the CDN and combine into a PDF."""
        # Build the signed token string (wildcard ACL covers all pages)
        token = (
            f"_token_="
            f"exp={token_parts['exp']}~"
            f"acl={token_parts['acl']}~"
            f"hmac={token_parts['hmac']}"
        )

        logger.info("calameo_pdf_start", bkcode=bkcode, pages=page_count)
        start = time.monotonic()

        page_bytes: dict[int, bytes] = {}
        batch_size = 10

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=25,
            headers={"User-Agent": _UA},
        ) as client:
            for batch_start in range(1, page_count + 1, batch_size):
                batch_end = min(batch_start + batch_size, page_count + 1)
                tasks = [
                    self._download_page(
                        client, key, n, token
                    )
                    for n in range(batch_start, batch_end)
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for n, res in zip(range(batch_start, batch_end), results):
                    if isinstance(res, bytes) and len(res) > 100:
                        page_bytes[n] = res
                    else:
                        logger.warning(
                            "calameo_page_skip",
                            page=n,
                            reason=(
                                str(res)[:80]
                                if isinstance(res, Exception)
                                else "empty"
                            ),
                        )

        if not page_bytes:
            logger.error("calameo_pdf_no_pages", bkcode=bkcode)
            return None

        ordered = [page_bytes[p] for p in sorted(page_bytes)]

        # Validate & normalise each image
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
                logger.warning("calameo_img_bad", page=i + 1,
                               err=str(exc)[:80])

        if not clean:
            return None

        fname = f"calameo_{bkcode}_{uuid.uuid4().hex[:8]}.pdf"
        pdf_path = PDF_DIR / fname
        try:
            pdf_data = img2pdf.convert(clean)
            pdf_path.write_bytes(pdf_data)
            elapsed = time.monotonic() - start
            logger.info(
                "calameo_pdf_done",
                bkcode=bkcode,
                pages=len(clean),
                size_kb=round(len(pdf_data) / 1024),
                elapsed=round(elapsed, 1),
            )
            return pdf_path
        except Exception as exc:
            logger.error("calameo_pdf_fail", error=str(exc)[:200])
            return None

    @staticmethod
    async def _download_page(
        client: httpx.AsyncClient,
        key: str,
        page_num: int,
        token: str,
    ) -> bytes:
        """Download a single page image from the signed CDN."""
        url = f"{_CDN_BASE}/{key}/p{page_num}.jpg?{token}"
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
    def _extract_book_code(url: str) -> Optional[str]:
        """
        Extract the book code from a Calameo URL.

        Supported patterns:
          /books/0000000012888bd5d54b6
          /username/books/0000000012888bd5d54b6
          /read/0000000012888bd5d54b6
          /username/read/0000000012888bd5d54b6
        """
        m = _BOOK_CODE_RE.search(url)
        return m.group(1) if m else None
