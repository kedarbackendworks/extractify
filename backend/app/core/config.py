"""
Extractify Backend – settings loaded from environment / .env file.
"""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = True
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000", "http://127.0.0.1:3001"]

    # ── MongoDB ──────────────────────────────────────
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "extractify"

    # ── Rate Limiting ────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 30

    # ── yt-dlp cookies ───────────────────────────────
    # Path to a Netscape-format cookies.txt file.
    # Enables extraction of auth-required content on
    # Instagram, Twitter/X, Facebook, etc.
    YTDLP_COOKIES_FILE: str = ""

    # ── Instagram Authentication ─────────────────────
    # Session ID from browser cookies — required for
    # stories, photos, and authenticated content.
    # Get it: DevTools → Application → Cookies → sessionid
    INSTAGRAM_SESSION_ID: str = ""
    INSTAGRAM_CSRF_TOKEN: str = ""
    INSTAGRAM_DS_USER_ID: str = ""
    # Path to Instagram-specific Netscape cookies file
    # (auto-generated from session ID if not provided)
    INSTAGRAM_COOKIES_FILE: str = ""

    # ── Facebook Authentication ──────────────────────
    # Required for downloading Stories, Photos, and authenticated content.
    # Get from: DevTools (F12) → Application → Cookies → facebook.com
    FACEBOOK_C_USER: str = ""
    FACEBOOK_XS: str = ""
    # Path to Facebook-specific Netscape cookies file
    FACEBOOK_COOKIES_FILE: str = ""

    # ── Twitter / X Authentication ───────────────────
    # Required for downloading videos, GIFs, and photos.
    # Get from: DevTools (F12) → Application → Cookies → x.com
    TWITTER_AUTH_TOKEN: str = ""
    TWITTER_CSRF_TOKEN: str = ""   # ct0 cookie value
    TWITTER_COOKIES_FILE: str = "" # Netscape cookies file (optional)
    # Public Bearer token used for Twitter GraphQL API requests.
    # This is the well-known guest bearer; rotate if revoked.
    TWITTER_BEARER_TOKEN: str = ""

    # ── Threads Authentication ─────────────────────
    THREADS_COOKIES_FILE: str = ""  # Netscape cookies file
    # GraphQL document IDs for Threads API queries
    THREADS_POST_DOC_ID: str = "26399684949649381"
    THREADS_USER_DOC_ID: str = "23904112853711550"
    # Meta/IG App ID used in Threads API headers
    THREADS_APP_ID: str = "238260118697367"

    # ── Instagram API identifiers ────────────────────
    # Instagram App IDs (desktop & mobile) and GraphQL query hash.
    # Defaults are the well-known public values; override if rotated.
    IG_APP_ID: str = "936619743392459"
    IG_MOBILE_APP_ID: str = "567067343352427"
    IG_GRAPHQL_POST_HASH: str = "b3055c01b4b222b8a47dc12b090e4e64"

    # ── Tumblr API ───────────────────────────────────
    # Comma-separated read-only consumer keys for the Tumblr v2 API.
    TUMBLR_API_KEYS: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
