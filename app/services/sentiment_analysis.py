"""
Sentiment Analysis service — implements Review.analyzeSentiment() from the
SRS Class Diagram, feeding US-08 (Neighborhood Vibe Report) and US-10
(Submit Neighborhood Reviews & Sentiment Feedback).
"""

from app.deepseek_client import DeepSeekUnavailableError, call_json
from app.schemas import ReviewIn, SentimentResult, VibeReport

SYSTEM_PROMPT = """You are a sentiment-analysis engine for neighborhood/venue reviews.
The review may be in Arabic or English.

Return ONLY a JSON object with exactly these fields:
{
  "sentiment_score": number from -1.0 (very negative) to 1.0 (very positive),
  "label": "negative" | "neutral" | "positive",
  "safety_mentioned": boolean,       // does the text discuss safety/crime/security?
  "quietness_mentioned": boolean,    // does the text discuss noise/quiet level?
  "amenities_mentioned": boolean     // does the text discuss nearby shops/transit/services?
}
"""


def analyze_review(review: ReviewIn) -> SentimentResult:
    """Scenario 1 (US-10 Happy Path): score a single review."""
    try:
        raw = call_json(SYSTEM_PROMPT, review.text)
    except DeepSeekUnavailableError:
        # NFR3.01: neutral fallback rather than failing the whole request.
        return SentimentResult(sentiment_score=0.0, label="neutral")

    return SentimentResult(
        sentiment_score=float(raw.get("sentiment_score", 0.0)),
        label=raw.get("label", "neutral"),
        safety_mentioned=bool(raw.get("safety_mentioned", False)),
        quietness_mentioned=bool(raw.get("quietness_mentioned", False)),
        amenities_mentioned=bool(raw.get("amenities_mentioned", False)),
    )


def aggregate_vibe_report(results: list[SentimentResult]) -> VibeReport:
    """
    US-08 Scenario 2 (Low Data Density Region): if there's too little
    review data, mark data_confidence as pending instead of faking scores.

    This is a simple, explainable aggregation for the MVP — swap in a
    weighted/decayed model later without touching the API contract.
    """
    if len(results) < 3:
        return VibeReport(
            safety_score=5.0,
            quietness_score=5.0,
            amenities_score=5.0,
            reviews_analyzed=len(results),
            data_confidence="pending_more_data",
        )

    def score_for(flag_attr: str) -> float:
        relevant = [r for r in results if getattr(r, flag_attr)]
        if not relevant:
            return 5.0  # neutral midpoint when nobody mentioned this dimension
        avg_sentiment = sum(r.sentiment_score for r in relevant) / len(relevant)
        # map [-1, 1] sentiment -> [0, 10] score
        return round((avg_sentiment + 1) * 5, 1)

    return VibeReport(
        safety_score=score_for("safety_mentioned"),
        quietness_score=score_for("quietness_mentioned"),
        amenities_score=score_for("amenities_mentioned"),
        reviews_analyzed=len(results),
        data_confidence="sufficient",
    )
