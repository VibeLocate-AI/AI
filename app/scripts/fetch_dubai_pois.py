"""
Pulls Points-of-Interest (POI) data for Dubai from OpenStreetMap via the
Overpass API — a free, no-signup alternative/complement to Foursquare OS
Places, used here because Foursquare's dataset is now gated behind a
Hugging Face access request.

This feeds the "Geo Intelligence" layer of the Vibe Report (US-08):
counting/classifying nearby POIs within the 500m radius around a property.

Usage:
    python -m app.scripts.fetch_dubai_pois

Output:
    data/dubai_pois.json — a flat list of POIs with lat/lon/category/name,
    ready to be loaded into PostgreSQL/PostGIS by the Backend developer.

NOTE: This script needs real internet access to overpass-api.de.
It could NOT be executed inside this sandbox (network here is restricted
to a small allowlist of package registries). Run it on your own machine
or inside the actual dev/CI environment.
"""

import json
import time
from pathlib import Path
from wsgiref import headers

import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Rough bounding box covering Dubai city (south, west, north, east).
# Good enough for an MVP demo; narrow it to a specific district later
# to keep result size and query time down.
DUBAI_BBOX = (25.00, 54.90, 25.35, 55.60)

# Map OSM tags -> our internal Vibe Report categories.
# (Safety / Quietness / Amenities are the 3 dimensions from the SRS
# Class Diagram's VibeReport entity.)
CATEGORY_TAGS = {
    "safety": [
        ("amenity", "police"),
        ("amenity", "hospital"),
        ("amenity", "clinic"),
    ],
    "quietness_positive": [
        ("leisure", "park"),
        ("landuse", "recreation_ground"),
    ],
    "quietness_negative": [
        ("amenity", "nightclub"),
        ("amenity", "bar"),
    ],
    "amenities": [
        ("amenity", "restaurant"),
        ("amenity", "cafe"),
        ("amenity", "pharmacy"),
        ("shop", "supermarket"),
        ("public_transport", "station"),
    ],
}


def build_overpass_query(bbox: tuple[float, float, float, float]) -> str:
    """Builds a single Overpass QL query that fetches every tag we care
    about in one request, instead of one request per category (Overpass's
    public server rate-limits aggressively, so batching matters)."""
    south, west, north, east = bbox
    clauses = []
    for tags in CATEGORY_TAGS.values():
        for key, value in tags:
            clauses.append(f'node["{key}"="{value}"]({south},{west},{north},{east});')
    body = "\n  ".join(clauses)
    return f"""
[out:json][timeout:60];
(
  {body}
);
out body;
"""


def category_for_tags(tags: dict) -> str | None:
    for category, kv_pairs in CATEGORY_TAGS.items():
        for key, value in kv_pairs:
            if tags.get(key) == value:
                return category
    return None


def fetch_dubai_pois() -> list[dict]:
    query = build_overpass_query(DUBAI_BBOX)
    headers = {
    "User-Agent": "VibeLocateAI-DataIngestion/0.1 (student project)",
    "Accept": "application/json",
    }
    response = requests.post(OVERPASS_URL, data={"data": query}, headers=headers, timeout=90)
    response.raise_for_status()
    elements = response.json().get("elements", [])

    pois = []
    for el in elements:
        tags = el.get("tags", {})
        pois.append({
            "osm_id": el["id"],
            "name": tags.get("name", "Unnamed"),
            "category": category_for_tags(tags),
            "latitude": el["lat"],
            "longitude": el["lon"],
        })
    return pois


def main():
    print("Fetching Dubai POIs from Overpass API... (can take 20-60s)")
    started = time.time()
    pois = fetch_dubai_pois()
    elapsed = time.time() - started

    out_dir = Path(__file__).resolve().parents[2] / "data"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "dubai_pois.json"
    out_path.write_text(json.dumps(pois, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Done in {elapsed:.1f}s — {len(pois)} POIs saved to {out_path}")


if __name__ == "__main__":
    main()
