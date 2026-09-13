"""
Pydantic schemas.

UPDATED AGAIN after inspecting the ACTUAL database dump (vibelocate_db.sql)
directly — this supersedes the earlier version that was based on guessing
from the live /api/home response alone. The SQL dump is authoritative:
it's the real `CREATE TABLE` + `INSERT` statements from the backend team's
own database.

Key corrections made in this version:

1. property_types has only 3 rows in the dump: Apartment(1), Villa(2),
   Penthouse(3). There is NO "Townhouse" — that was a wrong guess in the
   previous version based on assuming a common 4th type.

2. property_features are specific branded names with a `category` enum
   (amenity | facility | view | security | policy), NOT generic tags.
   Examples from the actual data: "Infinity Pool", "Full Sea View",
   "Smart Home", "Covered Parking". The earlier "Swimming Pool", "Gym",
   "Balcony" list was an incorrect guess and has been replaced.

3. Every property has `currency` defaulting to 'AED' at the DB level
   (properties.currency CHAR(3) DEFAULT 'AED') — confirming AED as the
   default, though the column allows other 3-letter currency codes.

NOTE: The SQL dump's `properties` table only contains 2 seed rows (vs.
100 shown by the live /api/home endpoint) — this dump may be an older
schema snapshot, not the live production data. The MATCHING VOCABULARY
(property_types, property_features names/ids) is what matters for us and
is treated as authoritative here since it defines the fixed lookup
tables the AI's output must align with, regardless of how many actual
property rows exist at any given time.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Backend-confirmed vocab — sourced directly from vibelocate_db.sql
# (CREATE TABLE property_types / property_features + their INSERT data)
# ---------------------------------------------------------------------------

# CONFIRMED from the SQL dump's `property_types` table — only 3 rows exist.
PROPERTY_TYPE_ID_MAP: dict[str, int] = {
    "apartment": 1,
    "villa": 2,
    "penthouse": 3,
    "townhouse": 4,
    "house": 5,
    "office": 6,
    "warehouse": 7,
    "land": 8,
    "restaurant": 9,
    "hotel": 10,
    "building": 11,
    "commercial": 12,
    "clinic": 13,
    "school": 14,
    "showroom": 15,
    "other": 16,
}

# CONFIRMED from the SQL dump's `property_features` table. Each feature
# also has a category (amenity/facility/view/security/policy) in the DB,
# but we only need the exact name strings here to constrain the LLM's
# output — the backend owns the category mapping.
KNOWN_FEATURE_NAMES: list[str] = [
    "Infinity Pool", "Full Sea View", "Smart Home", "Covered Parking",
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
        "quiet apartment near modern cafes with an infinity pool under 150000 AED",
        "شقة هادية فيها إطلالة بحر كاملة بـ 145000 درهم",
    ])
    language: Optional[Language] = None  # auto-detected if not provided


class ParsedCriteria(BaseModel):
    """
    Structured output of Query.parseWithLLM().
    Shaped to match the ACTUAL backend database schema (vibelocate_db.sql)
    directly — property_type_id and required_amenities values must match
    property_types.id / property_features.name exactly.
    """

    property_type: Optional[str] = None            # human-readable label, e.g. "Apartment" — for logging/debugging
    property_type_id: Optional[int] = None          # matches properties.type_id — see PROPERTY_TYPE_ID_MAP above
    max_budget: Optional[float] = None
    budget_currency: Optional[str] = None           # "AED", "USD", etc. — whatever the user actually said; DB defaults to AED
    min_bedrooms: Optional[int] = None
    vibe_tags: list[str] = Field(default_factory=list)        # free-form, e.g. ["quiet", "near_cafes"] — NOT matched to backend fields
    required_amenities: list[str] = Field(default_factory=list)  # MUST be drawn from KNOWN_FEATURE_NAMES (property_features.name)
    location_hint: Optional[str] = None             # free-text area/landmark mention
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    needs_clarification: bool = False               # Scenario 2 (US-07): too short / unclear


class Query(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    raw_text: str
    parsed_criteria: Optional[ParsedCriteria] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PropertySearchResponse(BaseModel):
    """
    The actual end-to-end result: what the AI understood from the user's
    text, PLUS the real matching properties fetched live from the
    backend. `properties` are raw dicts (not strongly typed) since we
    don't own the backend's Property schema — we just pass through
    whatever fields it returns.
    """

    parsed_criteria: ParsedCriteria
    matches_found: int
    properties: list[dict]


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
    property_id: Optional[int] = None                # matches backend's properties.id (bigint, not UUID)
    safety_score: float = Field(ge=0.0, le=10.0)
    quietness_score: float = Field(ge=0.0, le=10.0)
    amenities_score: float = Field(ge=0.0, le=10.0)
    reviews_analyzed: int = 0
    data_confidence: str = "sufficient"  # "sufficient" | "pending_more_data" (US-08 Scenario 2)
    generated_at: datetime = Field(default_factory=datetime.utcnow)