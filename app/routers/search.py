from fastapi import APIRouter

from app.schemas import ParsedCriteria, QueryRequest
from app.services.intent_recognition import parse_query

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("/ai-contextual", response_model=ParsedCriteria)
def ai_contextual_search(request: QueryRequest) -> ParsedCriteria:
    """
    US-07 — Natural Language AI Search.

    NOTE: this endpoint only does step 2-3 of the Sequence Diagram
    (query -> structured criteria). The Core Backend (Node.js) is the
    one that takes this output and runs the pgvector similarity search
    against Property.embedding, then returns ranked listings + Match
    Score to the client (step 4-6).
    """
    return parse_query(request)
