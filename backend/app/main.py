"""
Extractify Backend – FastAPI application factory.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import connect_db, close_db
from app.routes.extract import router as extract_router
from app.routes.health import router as health_router
from app.routes.download import router as download_router
from app.routes.files import router as files_router
from app.routes.reviews import router as reviews_router
from app.utils.browser import browser_pool
from app.utils.http_client import close_http_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    # ── Startup ──────────────────────────────────
    await connect_db()
    await browser_pool.start()
    yield
    # ── Shutdown ─────────────────────────────────
    await browser_pool.stop()
    await close_http_client()
    await close_db()


app = FastAPI(
    title="Extractify API",
    description="Content extraction backend for social media & document platforms",
    version="0.1.0",
    lifespan=lifespan,
)

# In development, allow common local/LAN origins in addition to explicit CORS_ORIGINS.
# This prevents local host/IP variations from failing browser preflight requests.
_DEV_LOCAL_ORIGIN_REGEX = (
    r"^https?://("
    r"localhost|127\.0\.0\.1|0\.0\.0\.0|"
    r"10(?:\.\d{1,3}){3}|"
    r"192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}|"
    r"[a-zA-Z0-9-]+"
    r")(?:\:\d+)?$"
)

allow_origin_regex = _DEV_LOCAL_ORIGIN_REGEX if settings.APP_ENV.lower() == "development" else None

# ── CORS ─────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ───────────────────────────────────────────
app.include_router(health_router)
app.include_router(extract_router)
app.include_router(download_router)
app.include_router(files_router)
app.include_router(reviews_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
    )
