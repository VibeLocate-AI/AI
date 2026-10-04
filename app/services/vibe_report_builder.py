"""
Build Neighborhood Vibe Reports for actual properties.

Pipeline:
property coordinates
    -> nearby POIs
    -> matching reviews
    -> ONE batch AI sentiment request
    -> aggregated Vibe Report
"""

import json
import logging
import math
from functools import lru_cache
from pathlib import Path

from app.schemas import ReviewIn, VibeReport
from app.services.sentiment_analysis import (
    aggregate_vibe_report,
    analyze_reviews_batch,
)


logger = logging.getLogger(
    "vibelocate.vibe_report_builder"
)


_DATA_DIR = (
    Path(__file__).resolve().parents[2]
    / "data"
)

_POIS_PATH = (
    _DATA_DIR
    / "dubai_pois.json"
)

_REVIEWS_PATH = (
    _DATA_DIR
    / "synthetic_reviews_pois.json"
)


RADIUS_METERS = 500.0
_EARTH_RADIUS_M = 6_371_000.0


def haversine_distance_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    d_phi = math.radians(
        lat2 - lat1
    )

    d_lambda = math.radians(
        lon2 - lon1
    )

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(d_lambda / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )

    return _EARTH_RADIUS_M * c


@lru_cache(maxsize=1)
def _load_pois() -> tuple[dict, ...]:

    if not _POIS_PATH.exists():
        logger.error(
            "POIs file not found at %s",
            _POIS_PATH,
        )
        return tuple()

    try:
        data = json.loads(
            _POIS_PATH.read_text(
                encoding="utf-8"
            )
        )

        logger.info(
            "Loaded %d POIs",
            len(data),
        )

        return tuple(data)

    except Exception:
        logger.exception(
            "Failed to load POIs"
        )
        return tuple()


@lru_cache(maxsize=1)
def _load_reviews() -> tuple[dict, ...]:

    if not _REVIEWS_PATH.exists():
        logger.error(
            "Reviews file not found at %s",
            _REVIEWS_PATH,
        )
        return tuple()

    try:
        data = json.loads(
            _REVIEWS_PATH.read_text(
                encoding="utf-8"
            )
        )

        logger.info(
            "Loaded %d reviews",
            len(data),
        )

        return tuple(data)

    except Exception:
        logger.exception(
            "Failed to load reviews"
        )
        return tuple()


def find_nearby_pois(
    latitude: float,
    longitude: float,
    pois,
    radius_m: float = RADIUS_METERS,
) -> list[dict]:

    nearby = []

    for poi in pois:

        poi_lat = poi.get("latitude")
        poi_lng = poi.get("longitude")

        if (
            poi_lat is None
            or poi_lng is None
        ):
            continue

        try:
            poi_lat = float(poi_lat)
            poi_lng = float(poi_lng)

        except (TypeError, ValueError):
            continue

        distance = haversine_distance_m(
            latitude,
            longitude,
            poi_lat,
            poi_lng,
        )

        if distance <= radius_m:
            nearby.append(poi)

    return nearby


@lru_cache(maxsize=1000)
def _build_cached_report(
    latitude: float,
    longitude: float,
) -> VibeReport:

    pois = _load_pois()
    all_reviews = _load_reviews()

    nearby_pois = find_nearby_pois(
        latitude,
        longitude,
        pois,
    )

    nearby_names = {
        poi.get("name")
        for poi in nearby_pois
        if poi.get("name")
    }

    matched_reviews = [
        review
        for review in all_reviews
        if (
            review.get("place_name")
            in nearby_names
            and review.get("text")
        )
    ]

    logger.info(
        "%d POIs within %.0fm, %d reviews matched",
        len(nearby_pois),
        RADIUS_METERS,
        len(matched_reviews),
    )

    review_inputs = [
        ReviewIn(
            text=str(review["text"]),
            source=str(
                review.get(
                    "source",
                    "synthetic_deepseek_v1",
                )
            ),
        )
        for review in matched_reviews
    ]

    sentiment_results = (
        analyze_reviews_batch(
            review_inputs
        )
    )

    return aggregate_vibe_report(
        sentiment_results
    )


def build_vibe_report_for_property(
    property_id: str,
    latitude: float,
    longitude: float,
) -> VibeReport:

    property_id = str(property_id)

    latitude = round(
        float(latitude),
        6,
    )

    longitude = round(
        float(longitude),
        6,
    )

    report = _build_cached_report(
        latitude,
        longitude,
    )

    return report.model_copy(
        update={
            "property_id": property_id,
        }
    )