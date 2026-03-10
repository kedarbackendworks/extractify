"""
Health-check route.
"""

from fastapi import APIRouter
from app.routes.schemas import HealthOut
from app.core.database import is_connected

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health():
    mongo_status = "connected" if is_connected() else "disconnected"
    return HealthOut(status="ok", mongo=mongo_status, version="0.1.0")
