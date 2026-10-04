"""
Unit tests that mock the DeepSeek call, so we can verify our parsing /
aggregation logic works correctly without needing a real API key or
network access. This is exactly what US-07's acceptance criteria and
Task list ask for ("Test NLP parsing accuracy... unit tests").
"""

from unittest.mock import patch

from app.schemas import QueryRequest, ReviewIn
from app.services import intent_recognition, sentiment_analysis


def test_parse_query_happy_path():
    fake_llm_output = {
        "property_type": "studio",
        "max_budget": 2000,
        "min_bedrooms": None,
        "vibe_tags": ["quiet", "near_cafes"],
        "required_amenities": ["fast_wifi"],
        "location_hint": None,
        "confidence": 0.92,
        "needs_clarification": False,
    }
    with patch("app.services.intent_recognition.call_json", return_value=fake_llm_output):
        result = intent_recognition.parse_query(
            QueryRequest(raw_text="quiet studio near modern cafes with fast wifi under $2000/month")
        )
    assert result.property_type == "studio"
    assert result.max_budget == 2000
    assert "quiet" in result.vibe_tags
    assert result.needs_clarification is False


def test_parse_query_unclear_prompt():
    fake_llm_output = {
        "property_type": None,
        "max_budget": None,
        "min_bedrooms": None,
        "vibe_tags": [],
        "required_amenities": [],
        "location_hint": None,
        "confidence": 0.1,
        "needs_clarification": True,
    }
    with patch("app.services.intent_recognition.call_json", return_value=fake_llm_output):
        result = intent_recognition.parse_query(QueryRequest(raw_text="Nice"))
    assert result.needs_clarification is True
    assert result.confidence < 0.3


def test_parse_query_degrades_gracefully_on_api_failure():
    from app.deepseek_client import DeepSeekUnavailableError

    with patch("app.services.intent_recognition.call_json", side_effect=DeepSeekUnavailableError("timeout")):
        result = intent_recognition.parse_query(QueryRequest(raw_text="anything"))
    assert result.needs_clarification is True
    assert result.confidence == 0.0


def test_analyze_review_positive():
    fake_llm_output = {
        "sentiment_score": 0.8,
        "label": "positive",
        "safety_mentioned": True,
        "quietness_mentioned": False,
        "amenities_mentioned": True,
    }
    with patch("app.services.sentiment_analysis.call_json", return_value=fake_llm_output):
        result = sentiment_analysis.analyze_review(ReviewIn(text="Super safe area, close to great shops!"))
    assert result.label == "positive"
    assert result.safety_mentioned is True


def test_aggregate_vibe_report_pending_more_data():
    # Fewer than 3 reviews -> Scenario 2 (Low Data Density Region)
    from app.schemas import SentimentResult

    results = [SentimentResult(sentiment_score=0.5, label="positive", safety_mentioned=True)]
    report = sentiment_analysis.aggregate_vibe_report(results)
    assert report.data_confidence == "pending_more_data"


def test_aggregate_vibe_report_sufficient_data():
    from app.schemas import SentimentResult

    results = [
        SentimentResult(sentiment_score=0.8, label="positive", safety_mentioned=True, quietness_mentioned=True),
        SentimentResult(sentiment_score=0.6, label="positive", safety_mentioned=True, amenities_mentioned=True),
        SentimentResult(sentiment_score=-0.2, label="negative", quietness_mentioned=True),
    ]
    report = sentiment_analysis.aggregate_vibe_report(results)
    assert report.data_confidence == "sufficient"
    assert 0 <= report.safety_score <= 10
    assert 0 <= report.quietness_score <= 10
