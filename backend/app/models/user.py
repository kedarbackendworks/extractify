"""
User document – optional auth support.
"""

from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import EmailStr, Field
from pymongo import ASCENDING, IndexModel


class User(Document):
    email: EmailStr
    hashed_password: str
    display_name: Optional[str] = None
    is_active: bool = True
    is_premium: bool = False
    daily_downloads: int = 0
    last_download_reset: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "users"
        indexes = [
            IndexModel([("email", ASCENDING)], unique=True),
        ]
