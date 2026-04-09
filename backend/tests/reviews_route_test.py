import asyncio

from app.models.review import ReviewCreate
from app.routes.reviews import submit_review


def _run(coro):
    return asyncio.run(coro)


def test_submit_review_success(monkeypatch):
    class FakeReview:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def insert(self):
            return self

    payload = ReviewCreate(
        name="Test User",
        email="test@example.com",
        review_text="Great app",
        rating=5,
    )

    monkeypatch.setattr("app.routes.reviews.Review", FakeReview)

    response = _run(submit_review(payload))

    assert response["status"] == "success"


def test_submit_review_handles_insert_failure(monkeypatch):
    class FailingReview:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def insert(self):
            raise RuntimeError("db unavailable")

    payload = ReviewCreate(
        name="Test User",
        email="test@example.com",
        review_text="Great app",
        rating=5,
    )

    monkeypatch.setattr("app.routes.reviews.Review", FailingReview)

    response = _run(submit_review(payload))

    assert response["status"] == "error"
