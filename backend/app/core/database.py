"""
MongoDB connection lifecycle managed by Beanie ODM + Motor.
"""

import structlog
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from app.core.config import settings

# We import all document models so Beanie can register them.
from app.models.job import Job
from app.models.user import User
from app.models.review import Review

logger = structlog.get_logger()

_client: AsyncIOMotorClient | None = None
_connected: bool = False


async def connect_db() -> None:
    """Open a Motor client and initialise Beanie document models."""
    global _client, _connected
    try:
        _client = AsyncIOMotorClient(
            settings.MONGO_URI,
            serverSelectionTimeoutMS=5000,  # fail fast (5s instead of 30s)
        )
        # Ping to verify connection
        await _client.admin.command("ping")
        await init_beanie(
            database=_client[settings.MONGO_DB_NAME],
            document_models=[Job, User, Review],
        )
        _connected = True
        logger.info("mongodb_connected", uri=settings.MONGO_URI, db=settings.MONGO_DB_NAME)
    except Exception as exc:
        _connected = False
        logger.error(
            "mongodb_connection_failed",
            error=str(exc),
            hint="Make sure MongoDB is running. You can use MongoDB Atlas (free) or install locally.",
        )


async def close_db() -> None:
    """Gracefully close the Motor client."""
    global _client, _connected
    if _client:
        _client.close()
        _client = None
        _connected = False


def is_connected() -> bool:
    return _connected
