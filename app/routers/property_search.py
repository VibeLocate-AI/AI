from fastapi import APIRouter

from app.schemas import PropertySearchResponse, QueryRequest
from app.services.intent_recognition import parse_query
from app.services.property_matcher import BackendUnavailableError, fetch_all_properties, match_properties

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("/find-properties", response_model=PropertySearchResponse)
def find_properties(request: QueryRequest) -> PropertySearchResponse:
    """
    THE full end-to-end flow: natural language text -> parsed criteria
    -> real properties fetched from the live backend -> matches.

    This is the answer to "what does the user actually get back" — as
    opposed to /api/search/ai-contextual, which only does the first half
    (text -> criteria) and leaves matching to the Core Backend.
    This endpoint does the matching itself for now (see
    property_matcher.py's docstring for why, and the plan to simplify
    once the backend exposes a real filter endpoint).
    """
    criteria = parse_query(request)

    if criteria.needs_clarification:
        return PropertySearchResponse(parsed_criteria=criteria, matches_found=0, properties=[])

    try:
        all_properties = fetch_all_properties()
    except BackendUnavailableError:
        # NFR3.01-style graceful degradation: the AI understood the
        # request fine, but we couldn't reach the property data right
        # now. Return the parsed criteria so the client can at least
        # show "here's what we understood" instead of a raw 500.
        return PropertySearchResponse(parsed_criteria=criteria, matches_found=0, properties=[])

    matches = match_properties(criteria, all_properties)
    return PropertySearchResponse(
        parsed_criteria=criteria,
        matches_found=len(matches),
        properties=matches,
    )