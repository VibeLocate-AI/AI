"""
Connects to the live Laravel backend to fetch real properties and match
them against the AI-parsed search criteria.

IMPORTANT — CURRENT LIMITATION (read before changing this file):
No dedicated search/filter endpoint has been confirmed with the backend
team yet — only GET /api/home, which returns all properties.

The exact JSON wrapper shape of /api/home has proven to be nested more
than one level deep (confirmed top-level keys: {"success", "data"}, but
`data` itself is not a bare list — it's wrapped further, e.g. Laravel's
default pagination shape {"data": [...], "links": ..., "meta": ...} or
a resource-collection wrapper). Rather than keep guessing key names one
level at a time, _find_property_list() below searches the JSON tree
(up to a few levels deep) for the first list of dicts that "looks like"
property records (has recognizable fields such as type_id/price/id),
and uses that — making this resilient to wrapper changes without
needing another round of manual inspection.

Once the backend confirms a real filter endpoint, replace this whole
client-side-filtering approach with a direct call.
"""

import logging

import httpx

from app.config import settings
from app.schemas import ParsedCriteria

logger = logging.getLogger("vibelocate.property_matcher")

# Fields we'd expect at least one of on a real property record. Used to
# distinguish "this is the properties list" from other lists that might
# appear in the payload (e.g. a list of filter options, categories...).
_PROPERTY_LIKE_FIELDS = {"type_id", "price", "bedrooms", "features", "id"}


class BackendUnavailableError(Exception):
    """Raised when the Laravel backend can't be reached or returns an error."""


def _looks_like_property_list(value) -> bool:
    if not isinstance(value, list) or not value:
        return False
    first = value[0]
    return isinstance(first, dict) and bool(_PROPERTY_LIKE_FIELDS & first.keys())


def _find_property_list(node, max_depth: int = 4, _depth: int = 0):
    """Recursively searches dicts/lists for the first list that looks
    like a list of property records. Returns None if nothing matches."""
    if _depth > max_depth:
        return None

    if _looks_like_property_list(node):
        return node

    if isinstance(node, dict):
        for value in node.values():
            found = _find_property_list(value, max_depth, _depth + 1)
            if found is not None:
                return found

    elif isinstance(node, list):
        for item in node:
            found = _find_property_list(item, max_depth, _depth + 1)
            if found is not None:
                return found

    return None


def fetch_all_properties() -> list[dict]:
    """
    Calls the confirmed-working GET /api/home endpoint and locates the
    actual properties list inside whatever wrapper shape it's using.
    """
    url = f"{settings.laravel_base_url}/api/home"
    try:
        response = httpx.get(url, timeout=settings.laravel_timeout_seconds)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        logger.error("Failed to fetch properties from backend: %s", exc)
        raise BackendUnavailableError(str(exc)) from exc

    properties = _find_property_list(data)
    if properties is not None:
        return properties

    # Nothing property-like found anywhere in the payload — log the
    # top-level shape so we have something concrete to inspect manually.
    shape_hint = list(data.keys()) if isinstance(data, dict) else type(data)
    logger.error("Could not locate a properties list anywhere in /api/home response. "
                 "Top-level shape: %s", shape_hint)
    raise BackendUnavailableError("Could not locate properties list in /api/home response")


def _feature_names(features_field) -> set[str]:
    names = set()
    for f in features_field or []:
        if isinstance(f, str):
            names.add(f)
        elif isinstance(f, dict) and "name" in f:
            names.add(f["name"])
    return names


def match_properties(
    criteria: ParsedCriteria,
    properties: list[dict],
    limit: int = 10,
) -> list[dict]:
    results = []

    for prop in properties:
        if criteria.property_type_id is not None:
            if prop.get("type_id") != criteria.property_type_id:
                continue

        if criteria.max_budget is not None:
            price = prop.get("price")
            try:
                if price is not None and float(price) > criteria.max_budget:
                    continue
            except (TypeError, ValueError):
                pass

        if criteria.min_bedrooms is not None:
            bedrooms = prop.get("bedrooms")
            if isinstance(bedrooms, (int, float)) and bedrooms < criteria.min_bedrooms:
                continue

        if criteria.required_amenities:
            prop_features = _feature_names(prop.get("features"))
            if not set(criteria.required_amenities).issubset(prop_features):
                continue

        results.append(prop)

    return results[:limit]