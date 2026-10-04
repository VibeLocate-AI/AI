"""
Property matching service.

Loads the current property catalog directly from the VibeLocate Laravel API
instead of the old local data/all_properties.json snapshot.

Live source:
GET /api/properties
"""

import logging
import os
from typing import Any

import httpx

from app.schemas import ParsedCriteria

logger = logging.getLogger("vibelocate.property_matcher")

LARAVEL_BASE_URL = os.getenv(
    "LARAVEL_BASE_URL",
    "https://vibelocate-laravel.onrender.com",
).rstrip("/")

PROPERTIES_ENDPOINT = f"{LARAVEL_BASE_URL}/api/properties"

REQUEST_TIMEOUT = 60.0


class BackendUnavailableError(Exception):
    """Raised when property data cannot be loaded from Laravel."""


def fetch_all_properties() -> list[dict]:
    """
    Fetch the complete property catalog from the Laravel backend.

    Expected Laravel response:
    {
        "success": true,
        "data": [...]
    }
    """

    try:
        with httpx.Client(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        ) as client:
            response = client.get(
                PROPERTIES_ENDPOINT,
                headers={
                    "Accept": "application/json",
                },
            )

            response.raise_for_status()
            payload = response.json()

    except httpx.HTTPStatusError as exc:
        logger.error(
            "Laravel returned HTTP %s while loading properties",
            exc.response.status_code,
        )
        raise BackendUnavailableError(
            f"Laravel returned HTTP {exc.response.status_code}"
        ) from exc

    except httpx.RequestError as exc:
        logger.error("Could not connect to Laravel: %s", exc)
        raise BackendUnavailableError(
            "Could not connect to Laravel property API"
        ) from exc

    except ValueError as exc:
        logger.error("Laravel returned invalid JSON: %s", exc)
        raise BackendUnavailableError(
            "Laravel returned invalid JSON"
        ) from exc

    if not isinstance(payload, dict):
        raise BackendUnavailableError(
            "Unexpected Laravel response format"
        )

    if payload.get("success") is not True:
        raise BackendUnavailableError(
            payload.get("message", "Laravel property request failed")
        )

    properties = payload.get("data")

    if not isinstance(properties, list):
        raise BackendUnavailableError(
            "Laravel response does not contain a valid data list"
        )

    logger.info(
        "fetch_all_properties(): loaded %d properties from Laravel",
        len(properties),
    )

    return properties


def _text_matches(needle: str, haystack: Any) -> bool:
    """Case-insensitive substring matching."""

    if not needle or haystack is None:
        return False

    return needle.strip().casefold() in str(haystack).strip().casefold()


def _property_type_values(prop: dict) -> list[Any]:
    """
    Build searchable property-type values from the current Laravel schema.

    Laravel currently exposes type_id but the human-readable property type
    may also appear in property_type/type/type_name depending on the endpoint.
    """

    values = [
        prop.get("property_type"),
        prop.get("type"),
        prop.get("type_name"),
    ]

    type_id = prop.get("type_id")

    # Must match the property_types table in Laravel/MySQL.
    type_map = {
        1: "Apartment",
        2: "Villa",
        3: "Penthouse",
        4: "Townhouse",
        5: "House",
        6: "Office",
        7: "Warehouse",
        8: "Land",
        9: "Restaurant",
        10: "Hotel",
        11: "Building",
        12: "Commercial Shop",
        13: "Clinic",
        14: "School",
        15: "Showroom",
        16: "Cafe",
    }

    try:
        normalized_id = int(type_id) if type_id is not None else None
    except (TypeError, ValueError):
        normalized_id = None

    if normalized_id in type_map:
        values.append(type_map[normalized_id])

    return [value for value in values if value]


def _location_values(prop: dict) -> list[Any]:
    """
    Collect searchable location text from the current Laravel response.

    Supports both English and Arabic neighborhood names returned by Laravel.
    """

    values = [
        prop.get("community"),
        prop.get("community_en"),
        prop.get("community_ar"),
        prop.get("neighborhood"),
        prop.get("neighborhood_en"),
        prop.get("neighborhood_ar"),
        prop.get("city"),
        prop.get("city_en"),
        prop.get("city_ar"),
        prop.get("emirate"),
        prop.get("emirate_en"),
        prop.get("emirate_ar"),
        prop.get("address"),
        prop.get("address_line_1"),
        prop.get("title"),
        prop.get("description"),
    ]

    location = prop.get("location")

    if isinstance(location, dict):
        values.extend(
            [
                location.get("address_line_1"),
                location.get("address_line_2"),
                location.get("building_name"),

                location.get("community"),
                location.get("community_en"),
                location.get("community_ar"),

                location.get("neighborhood"),
                location.get("neighborhood_name"),
                location.get("neighborhood_en"),
                location.get("neighborhood_ar"),

                location.get("city"),
                location.get("city_en"),
                location.get("city_ar"),

                location.get("emirate"),
                location.get("emirate_en"),
                location.get("emirate_ar"),
            ]
        )

    return [value for value in values if value]


def _matches_property_type(criteria_type: str, prop: dict) -> bool:
    """Match the requested property type against Laravel property data."""

    requested = criteria_type.strip().casefold()

    aliases = {
        "café": {"café", "cafe"},
        "cafe": {"café", "cafe"},
        "commercial shop": {
            "commercial shop",
            "shop",
            "commercial",
        },
    }

    requested_values = aliases.get(requested, {requested})

    for value in _property_type_values(prop):
        current = str(value).strip().casefold()

        if current in requested_values:
            return True

    return False


def match_properties(
    criteria: ParsedCriteria,
    properties: list[dict],
    limit: int = 10,
) -> list[dict]:
    """
    Match ParsedCriteria against properties returned by Laravel.

    Supported filters:
    - property type
    - minimum budget
    - maximum budget
    - minimum bedrooms
    - maximum bedrooms
    - location

    required_amenities and vibe_tags remain advisory because the imported
    properties currently do not contain reliable feature data.
    """

    results: list[dict] = []

    for prop in properties:

        # ---------------------------------------------------------------
        # Property type
        # ---------------------------------------------------------------

        if criteria.property_type:
            if not _matches_property_type(
                criteria.property_type,
                prop,
            ):
                continue

        # ---------------------------------------------------------------
        # Budget range
        # ---------------------------------------------------------------

        if (
            criteria.min_budget is not None
            or criteria.max_budget is not None
        ):
            price = prop.get("price")

            try:
                if price is None:
                    continue

                price = float(price)

                if (
                    criteria.min_budget is not None
                    and price < float(criteria.min_budget)
                ):
                    continue

                if (
                    criteria.max_budget is not None
                    and price > float(criteria.max_budget)
                ):
                    continue

            except (TypeError, ValueError):
                continue

        # ---------------------------------------------------------------
        # Bedroom range
        # ---------------------------------------------------------------

        if (
            criteria.min_bedrooms is not None
            or criteria.max_bedrooms is not None
        ):
            bedrooms = prop.get("bedrooms")

            try:
                if bedrooms is None:
                    continue

                bedrooms = int(bedrooms)

                if (
                    criteria.min_bedrooms is not None
                    and bedrooms < int(criteria.min_bedrooms)
                ):
                    continue

                if (
                    criteria.max_bedrooms is not None
                    and bedrooms > int(criteria.max_bedrooms)
                ):
                    continue

            except (TypeError, ValueError):
                continue

        # ---------------------------------------------------------------
        # Location
        # ---------------------------------------------------------------

        if criteria.location_hint:
            if not any(
                _text_matches(criteria.location_hint, value)
                for value in _location_values(prop)
            ):
                continue

        results.append(prop)

        if len(results) >= limit:
            break

    logger.info(
        "match_properties(): %d matches returned from %d properties",
        len(results),
        len(properties),
    )

    return results