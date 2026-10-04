from fastapi import APIRouter

from app.schemas import ReviewIn, SentimentResult, VibeReport
from app.services.sentiment_analysis import aggregate_vibe_report, analyze_review

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.post("/analyze", response_model=SentimentResult)
def analyze_single_review(review: ReviewIn) -> SentimentResult:
    """US-10 — score one review as it's submitted."""
    return analyze_review(review)


@router.post("/vibe-report", response_model=VibeReport)
def build_vibe_report(reviews: list[ReviewIn]) -> VibeReport:
    """
    US-08 — Neighborhood Vibe Report.

    In production this is called by the Core Backend with the set of
    reviews found within the 500m PostGIS radius query around a
    property. Here we just do the AI half: sentiment -> aggregate scores.
    """
    results = [analyze_review(r) for r in reviews]
    return aggregate_vibe_report(results)
