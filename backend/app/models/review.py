from datetime import datetime
from typing import Optional
from beanie import Document
from pydantic import BaseModel, EmailStr, Field
from pymongo import DESCENDING, IndexModel

class ReviewCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    review_text: str = Field(..., min_length=2, max_length=2000)
    rating: int = Field(..., ge=1, le=5)

class Review(Document):
    name: str
    email: str
    review_text: str
    rating: int
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "reviews" # MongoDB collection name
        indexes = [
            IndexModel([("created_at", DESCENDING)]),
        ]
