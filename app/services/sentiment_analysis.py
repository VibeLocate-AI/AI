"""
Sentiment Analysis service.

Supports:
- Single-review sentiment analysis.
- Batch review sentiment analysis for fast Vibe Report generation.
"""

import json

from app.deepseek_client import DeepSeekUnavailableError, call_json
from app.schemas import ReviewIn, SentimentResult, VibeReport


SYSTEM_PROMPT = """
You are a sentiment-analysis engine for neighborhood/venue reviews.

The reviews may be in Arabic or English.

Return ONLY a JSON object with exactly this structure:

{
  "results": [
    {
      "index": 0,
      "sentiment_score": 0.0,
      "label": "negative",
      "safety_mentioned": false,
      "quietness_mentioned": false,
      "amenities_mentioned": false
    }
  ]
}

Rules:
- Return exactly one result for every supplied review.
- Keep the same index as the input review.
- sentiment_score must be between -1.0 and 1.0.
- label must be "negative", "neutral", or "positive".
- safety_mentioned indicates discussion of safety, crime, or security.
- quietness_mentioned indicates discussion of noise or quietness.
- amenities_mentioned indicates discussion of nearby shops, transport,
  facilities, or services.
"""


SINGLE_REVIEW_SYSTEM_PROMPT = """
You are a sentiment-analysis engine for neighborhood/venue reviews.
The review may be in Arabic or English.

Return ONLY a JSON object with exactly these fields:

{
  "sentiment_score": 0.0,
  "label": "negative",
  "safety_mentioned": false,
  "quietness_mentioned": false,
  "amenities_mentioned": false
}

sentiment_score must be between -1.0 and 1.0.
label must be "negative", "neutral", or "positive".
"""


def _neutral_result() -> SentimentResult:
    return SentimentResult(
        sentiment_score=0.0,
        label="neutral",
        safety_mentioned=False,
        quietness_mentioned=False,
        amenities_mentioned=False,
    )


def analyze_review(review: ReviewIn) -> SentimentResult:
    """
    Analyze one review.

    Kept for endpoints that analyze a single submitted review.
    """

    try:
        raw = call_json(
            SINGLE_REVIEW_SYSTEM_PROMPT,
            review.text,
        )

    except DeepSeekUnavailableError:
        return _neutral_result()

    try:
        score = float(
            raw.get("sentiment_score", 0.0)
        )

        score = max(-1.0, min(1.0, score))

        label = raw.get("label", "neutral")

        if label not in {
            "negative",
            "neutral",
            "positive",
        }:
            label = "neutral"

        return SentimentResult(
            sentiment_score=score,
            label=label,
            safety_mentioned=bool(
                raw.get(
                    "safety_mentioned",
                    False,
                )
            ),
            quietness_mentioned=bool(
                raw.get(
                    "quietness_mentioned",
                    False,
                )
            ),
            amenities_mentioned=bool(
                raw.get(
                    "amenities_mentioned",
                    False,
                )
            ),
        )

    except (TypeError, ValueError):
        return _neutral_result()


def analyze_reviews_batch(
    reviews: list[ReviewIn],
) -> list[SentimentResult]:
    """
    Analyze multiple reviews using ONE LLM request.

    This is used by the Property Vibe Report to avoid one
    external AI request per review.
    """

    if not reviews:
        return []

    payload = {
        "reviews": [
            {
                "index": index,
                "text": review.text,
            }
            for index, review in enumerate(reviews)
        ]
    }

    try:
        raw = call_json(
            SYSTEM_PROMPT,
            json.dumps(
                payload,
                ensure_ascii=False,
            ),
        )

    except DeepSeekUnavailableError:
        return [
            _neutral_result()
            for _ in reviews
        ]

    raw_results = raw.get("results")

    if not isinstance(raw_results, list):
        return [
            _neutral_result()
            for _ in reviews
        ]

    parsed_by_index = {}

    for item in raw_results:
        if not isinstance(item, dict):
            continue

        try:
            index = int(item.get("index"))

            if index < 0 or index >= len(reviews):
                continue

            score = float(
                item.get(
                    "sentiment_score",
                    0.0,
                )
            )

            score = max(
                -1.0,
                min(1.0, score),
            )

            label = item.get(
                "label",
                "neutral",
            )

            if label not in {
                "negative",
                "neutral",
                "positive",
            }:
                label = "neutral"

            parsed_by_index[index] = SentimentResult(
                sentiment_score=score,
                label=label,
                safety_mentioned=bool(
                    item.get(
                        "safety_mentioned",
                        False,
                    )
                ),
                quietness_mentioned=bool(
                    item.get(
                        "quietness_mentioned",
                        False,
                    )
                ),
                amenities_mentioned=bool(
                    item.get(
                        "amenities_mentioned",
                        False,
                    )
                ),
            )

        except (TypeError, ValueError):
            continue

    return [
        parsed_by_index.get(
            index,
            _neutral_result(),
        )
        for index in range(len(reviews))
    ]


def aggregate_vibe_report(
    results: list[SentimentResult],
) -> VibeReport:
    """
    Aggregate sentiment results into the Vibe Report.
    """

    if len(results) < 3:
        return VibeReport(
            safety_score=5.0,
            quietness_score=5.0,
            amenities_score=5.0,
            reviews_analyzed=len(results),
            data_confidence="pending_more_data",
        )

    def score_for(
        flag_attr: str,
    ) -> float:

        relevant = [
            result
            for result in results
            if getattr(
                result,
                flag_attr,
            )
        ]

        if not relevant:
            return 5.0

        avg_sentiment = (
            sum(
                result.sentiment_score
                for result in relevant
            )
            / len(relevant)
        )

        return round(
            (avg_sentiment + 1) * 5,
            1,
        )

    return VibeReport(
        safety_score=score_for(
            "safety_mentioned"
        ),
        quietness_score=score_for(
            "quietness_mentioned"
        ),
        amenities_score=score_for(
            "amenities_mentioned"
        ),
        reviews_analyzed=len(results),
        data_confidence="sufficient",
    )