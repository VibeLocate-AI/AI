"""
Pydantic schemas used by the VibeLocate AI service.

These schemas define the request/response structures used by natural
language property search, property matching, sentiment analysis,
and Vibe Reports.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Property type vocabulary
# ---------------------------------------------------------------------------
KNOWN_PROPERTY_TYPES: list[str] = [
    "Apartment",
    "Villa",
    "Penthouse",
    "Townhouse",
    "House",
    "Office",
    "Warehouse",
    "Land",
    "Restaurant",
    "Hotel",
    "Building",
    "Commercial Shop",
    "Clinic",
    "School",
    "Showroom",
    "Cafe",
]

# No reliable property-features dataset is currently available.
KNOWN_FEATURE_NAMES: list[str] = []


# ---------------------------------------------------------------------------
# Natural Language AI Search
# ---------------------------------------------------------------------------

class Language(str, Enum):
    ar = "ar"
    en = "en"


class QueryRequest(BaseModel):
    """
    Request body for POST /api/search/ai-contextual.
    """

    raw_text: str = Field(
        ...,
        min_length=1,
        examples=[
            "I want a 2 bedroom apartment for rent in Dubai Marina",
            "أريد شقة غرفتين للإيجار في مرسى دبي",
        ],
    )

    language: Optional[Language] = None


class ParsedCriteria(BaseModel):
    """
    Structured search criteria extracted from natural language.
    """

    property_type: Optional[str] = None

    action_type: Optional[str] = None

    min_budget: Optional[float] = None

    max_budget: Optional[float] = None

    budget_currency: Optional[str] = None

    min_bedrooms: Optional[int] = None

    max_bedrooms: Optional[int] = None

    vibe_tags: list[str] = Field(
        default_factory=list
    )

    required_amenities: list[str] = Field(
        default_factory=list
    )

    location_hint: Optional[str] = None

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        default=0.0,
    )

    needs_clarification: bool = False


class Query(BaseModel):
    id: UUID = Field(
        default_factory=uuid4
    )

    raw_text: str

    parsed_criteria: Optional[ParsedCriteria] = None

    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )


class PropertySearchResponse(BaseModel):
    """
    AI-understood search criteria plus matching properties.
    """

    parsed_criteria: ParsedCriteria

    matches_found: int

    properties: list[dict]


# ---------------------------------------------------------------------------
# Sentiment Analysis / Vibe Report
# ---------------------------------------------------------------------------

class ReviewIn(BaseModel):
    """
    A single review to be analyzed.
    """

    text: str = Field(
        ...,
        min_length=1
    )

    source: str = "synthetic_deepseek_v1"


class SentimentResult(BaseModel):
    sentiment_score: float = Field(
        ge=-1.0,
        le=1.0
    )

    label: str

    safety_mentioned: bool = False

    quietness_mentioned: bool = False

    amenities_mentioned: bool = False


class VibeReport(BaseModel):
    property_id: Optional[str] = None

    safety_score: float = Field(
        ge=0.0,
        le=10.0
    )

    quietness_score: float = Field(
        ge=0.0,
        le=10.0
    )

    amenities_score: float = Field(
        ge=0.0,
        le=10.0
    )

    reviews_analyzed: int = 0

    data_confidence: str = "sufficient"

    generated_at: datetime = Field(
        default_factory=datetime.utcnow
    )


class PropertyVibeRequest(BaseModel):
    """
    Request body for POST /api/properties/vibe-report.
    """

    property_id: str = Field(
        ...,
        examples=["PROP_10211"]
    )

    latitude: float = Field(
        ...,
        examples=[25.21227]
    )

    longitude: float = Field(
        ...,
        examples=[55.27946]
    )