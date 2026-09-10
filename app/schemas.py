"""
Pydantic schemas.

UPDATED after inspecting the live backend API
(https://vibelocate-laravel.onrender.com/api/home) directly. Key findings
that changed this file vs. the original draft:

1. Properties use a numeric `type_id`, NOT a free-text property_type string.
   Inferred mapping (from titles in the API response — NOT yet confirmed
   directly with the backend team, flag this as an assumption):
       1 = Apartment, 2 = Villa, 3 = Penthouse, 4 = Townhouse

2. Amenities/features come from a fixed, specific vocabulary
   (e.g. "Swimming Pool", "Gym", "24/7 Security", "Balcony"...), not
   arbitrary free-form tags like "fast_wifi".

3. Currency is AED, not USD. We no longer assume USD — we now extract
   whichever currency the user actually said, and let the backend handle
   any conversion/filtering.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Backend-confirmed (or inferred-pending-confirmation) vocab
# ---------------------------------------------------------------------------

# ASSUMPTION — inferred from live API response titles, not yet confirmed
# by the backend team. Verify against their `property_types` table /
# endpoint before relying on this in production.
PROPERTY_TYPE_ID_MAP: dict[str, int] = {
    "apartment": 1,
    "villa": 2,
    "penthouse": 3,
    "townhouse": 4,
}

# Exact feature/amenity names observed in the live API's `features[].name`
# field. The LLM is instructed to only pick from this list (see
# intent_recognition.py SYSTEM_PROMPT) so its output can be matched
# directly against the backend's data without fuzzy string matching.
KNOWN_FEATURE_NAMES: list[str] = [
    "Swimming Pool", "Gym", "Parking", "24/7 Security", "Balcony",
    "Central Air Conditioning", "Elevator", "Concierge", "Kids Play Area",
    "Garden", "Sea View", "BBQ Area", "Jacuzzi", "Smart Home",
]


# ---------------------------------------------------------------------------
# US-07 — Natural Language AI Search / R2.02
# ---------------------------------------------------------------------------

class Language(str, Enum):
    ar = "ar"
    en = "en"


class QueryRequest(BaseModel):
    """What the Flutter client sends to POST /api/search/ai-contextual."""

    raw_text: str = Field(..., min_length=1, examples=[
        "quiet apartment near modern cafes with fast wifi under 2000 dollars",
        "شقة هادية قريبة من كافيهات فيها واي فاي سريع تحت 7000 درهم",
    ])
    language: Optional[Language] = None  # auto-detected if not provided


class ParsedCriteria(BaseModel):
    """
    Structured output of Query.parseWithLLM().
    Shaped to match the live backend's property schema directly —
    the Core Backend should be able to use type_id and feature names
    with no extra translation layer.
    """

    property_type: Optional[str] = None            # human-readable label, e.g. "Apartment" — for logging/debugging
    property_type_id: Optional[int] = None          # matches backend's properties.type_id — SEE PROPERTY_TYPE_ID_MAP ASSUMPTION ABOVE
    max_budget: Optional[float] = None
    budget_currency: Optional[str] = None           # "AED", "USD", etc. — whatever the user actually said; no assumed conversion
    min_bedrooms: Optional[int] = None
    vibe_tags: list[str] = Field(default_factory=list)        # ["quiet", "near_cafes"] — free-form, NOT matched to backend fields
    required_amenities: list[str] = Field(default_factory=list)  # MUST be drawn from KNOWN_FEATURE_NAMES
    location_hint: Optional[str] = None             # free-text area/landmark mention
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    needs_clarification: bool = False               # Scenario 2 (US-07): too short / unclear


class Query(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    raw_text: str
    parsed_criteria: Optional[ParsedCriteria] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# US-08 / US-10 — Sentiment Analysis & Vibe Report
# ---------------------------------------------------------------------------

class ReviewIn(BaseModel):
    """A single review to be scored, e.g. pulled from the seeded/synthetic dataset."""

    text: str = Field(..., min_length=1)
    source: str = "synthetic_deepseek_v1"


class SentimentResult(BaseModel):
    sentiment_score: float = Field(ge=-1.0, le=1.0)  # -1 negative ... +1 positive
    label: str                                        # "negative" | "neutral" | "positive"
    safety_mentioned: bool = False
    quietness_mentioned: bool = False
    amenities_mentioned: bool = False


class VibeReport(BaseModel):
    property_id: Optional[int] = None                # matches backend's properties.id (int, not UUID)
    safety_score: float = Field(ge=0.0, le=10.0)
    quietness_score: float = Field(ge=0.0, le=10.0)
    amenities_score: float = Field(ge=0.0, le=10.0)
    reviews_analyzed: int = 0
    data_confidence: str = "sufficient"  # "sufficient" | "pending_more_data" (US-08 Scenario 2)
    generated_at: datetime = Field(default_factory=datetime.utcnow)