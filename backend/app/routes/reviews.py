from fastapi import APIRouter
import structlog
from app.models.review import Review, ReviewCreate
from app.core.config import settings

router = APIRouter(prefix="/api/reviews", tags=["reviews"])
logger = structlog.get_logger()

@router.post("")
async def submit_review(data: ReviewCreate):
    """
    Accepts a user review (name, email, text, rating) and saves it to MongoDB.
    """
    try:
        review_doc = Review(
            name=data.name,
            email=data.email,
            review_text=data.review_text,
            rating=data.rating
        )
        await review_doc.insert()
        logger.info("review_submitted", email=data.email, rating=data.rating, ds_uri=settings.MONGO_URI)
        return {"status": "success", "message": "Review submitted successfully"}
    except Exception as exc:
        logger.error("review_submission_failed", error=str(exc))
        return {"status": "error", "message": "Failed to submit review"}
