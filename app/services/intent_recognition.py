"""
Intent Recognition service — implements US-07 (Natural Language AI Search).

Matches the backend's ACTUAL database schema (vibelocate_db.sql), not a
guessed one — see schemas.py for the full rationale behind
PROPERTY_TYPE_ID_MAP and KNOWN_FEATURE_NAMES.
"""

from app.deepseek_client import DeepSeekUnavailableError, call_json
from app.schemas import KNOWN_FEATURE_NAMES, PROPERTY_TYPE_ID_MAP, ParsedCriteria, QueryRequest

_FEATURE_LIST_STR = ", ".join(f'"{f}"' for f in KNOWN_FEATURE_NAMES)
_TYPE_LIST_STR = ", ".join(f'"{name.capitalize()}"' for name in PROPERTY_TYPE_ID_MAP)

SYSTEM_PROMPT = f"""You are an intent-extraction engine for a rental search app.
The user writes in Arabic or English, describing what kind of home they want.
Extract structured search criteria from their text.

Return ONLY a JSON object with exactly these fields:
{{
  "property_type": string or null,        // MUST be one of: {_TYPE_LIST_STR}, or null if not mentioned/unclear
  "max_budget": number or null,            // numeric only, no currency symbol
  "budget_currency": string or null,       // e.g. "AED", "USD" — whatever currency the user actually stated. If they said a plain number with no currency, use null (do NOT assume USD or AED).
  "min_bedrooms": integer or null,
  "vibe_tags": array of short lowercase English tags (e.g. ["quiet", "modern", "near_cafes"]),
  "required_amenities": array of amenities, EACH must be an EXACT match from this fixed list: [{_FEATURE_LIST_STR}]. Do not invent amenities outside this list — if the user mentions something not on the list (e.g. "gym" or "wifi"), put a descriptive tag in vibe_tags instead, not required_amenities.
  "location_hint": string or null,         // any neighborhood/landmark mentioned, verbatim
  "confidence": number 0.0-1.0,            // how confident you are in this extraction
  "needs_clarification": boolean           // true if the text is too short/vague to search on
}}

Rules:
- If the text is a single vague word (e.g. "nice", "حلو") set needs_clarification=true
  and confidence below 0.3.
- Never invent a budget, currency, or bedroom count that isn't stated or clearly implied.
- vibe_tags and required_amenities must always be arrays, even if empty.
- property_type must match the fixed list exactly (capitalized) or be null — never invent a new type (e.g. never output "Townhouse" or "Studio").
"""


def parse_query(request: QueryRequest) -> ParsedCriteria:
    """
    Scenario 1 (Happy Path): normal query -> full structured criteria.
    Scenario 2 (Unclear/short prompt): returns needs_clarification=True
    instead of raising, so the API can prompt the user (per US-07 spec).
    """
    try:
        raw = call_json(SYSTEM_PROMPT, request.raw_text)
    except DeepSeekUnavailableError:
        # NFR3.01: degrade gracefully rather than 500ing the client.
        return ParsedCriteria(confidence=0.0, needs_clarification=True)

    property_type = raw.get("property_type")
    property_type_id = None
    if property_type:
        property_type_id = PROPERTY_TYPE_ID_MAP.get(property_type.lower())

    # Defensive filter: even though the prompt constrains the model, LLMs
    # occasionally drift. Silently drop any amenity that isn't in our
    # known vocabulary rather than passing garbage on to the backend.
    raw_amenities = raw.get("required_amenities") or []
    valid_amenities = [a for a in raw_amenities if a in KNOWN_FEATURE_NAMES]

    return ParsedCriteria(
        property_type=property_type,
        property_type_id=property_type_id,
        max_budget=raw.get("max_budget"),
        budget_currency=raw.get("budget_currency"),
        min_bedrooms=raw.get("min_bedrooms"),
        vibe_tags=raw.get("vibe_tags") or [],
        required_amenities=valid_amenities,
        location_hint=raw.get("location_hint"),
        confidence=float(raw.get("confidence", 0.0)),
        needs_clarification=bool(raw.get("needs_clarification", False)),
    )
