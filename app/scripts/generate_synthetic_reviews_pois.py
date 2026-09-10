"""
Generates synthetic-but-realistic reviews for the real Dubai POIs already
pulled from OpenStreetMap (data/dubai_pois.json — see
app/scripts/fetch_dubai_pois.py). Unlike generate_synthetic_reviews.py
(restaurants only, from the TripAdvisor CSV), this script covers ALL
Vibe Report dimensions — safety, quietness, and amenities — because it
reuses the same POIs that already feed the Geo Intelligence layer.

WHY THIS EXISTS (same justification as generate_synthetic_reviews.py):
No open, real, review-text dataset with solid Dubai coverage exists for
non-restaurant venues (pharmacies, parks, clinics, etc.). Mirroring the
SRS's own approach with the seeded Yelp dataset (Limitations 1.4), we
generate realistic synthetic reviews for MVP/demo purposes only — always
tagged source="synthetic_deepseek_v1" so real and synthetic data are
never confused, and documented as a project Limitation.

Usage:
    py -m app.scripts.generate_synthetic_reviews_pois --n-pois 30 --category amenities
    py -m app.scripts.generate_synthetic_reviews_pois --n-pois 50   # all categories mixed
"""

import argparse
import json
import time
from pathlib import Path

from app.deepseek_client import DeepSeekUnavailableError, call_json

# Category-specific guidance so a pharmacy review doesn't read like a
# park review. Mirrors the CATEGORY_TAGS groupings from fetch_dubai_pois.py
# and the three VibeReport dimensions (safety / quietness / amenities).
CATEGORY_GUIDANCE_ALL = """
- safety (hospital/clinic/police): safety, cleanliness, how reassuring it feels
- quietness_positive (park): calm, green, peaceful (occasionally crowded)
- quietness_negative (bar/nightclub): noise levels at night, manageable or disruptive
- amenities (restaurant/cafe/pharmacy/supermarket/transit): quality, convenience for daily life
"""

SYSTEM_PROMPT_BATCH = f"""You are generating realistic-sounding neighborhood
reviews for a student software project's demo dataset (NOT real user data —
this will be clearly labeled as synthetic).

You will be given a list of places, each with a category. Category guidance:
{CATEGORY_GUIDANCE_ALL}

For EACH place in the list, write the requested number of short reviews (1-2
sentences, realistic tone, not exaggerated) appropriate to its category. Vary
sentiment (some positive, some mixed, occasionally critical) across reviews
for the same place. Write some reviews in English and some in Arabic, mixed
naturally across the whole batch.

Return ONLY a JSON object:
{{
  "results": [
    {{
      "place_name": "<exact name as given>",
      "reviews": [{{"text": "...", "language": "en" or "ar"}}, ...]
    }},
    ...
  ]
}}
One entry per place, in the same order as given.
"""


def build_batch_user_prompt(pois: list[dict], reviews_per_poi: int) -> str:
    lines = [f'- "{p["name"]}" (category: {p.get("category", "amenities")})' for p in pois]
    return (
        f"Generate {reviews_per_poi} reviews for EACH of these {len(pois)} places:\n"
        + "\n".join(lines)
    )


def generate_for_poi_batch(pois: list[dict], reviews_per_poi: int) -> list[dict]:
    """One API call covers `pois` (typically 5) instead of one call each —
    this is the main lever for speed: fewer total requests means less
    total wait time AND fewer 429s on a busy shared free-tier model."""
    try:
        raw = call_json(SYSTEM_PROMPT_BATCH, build_batch_user_prompt(pois, reviews_per_poi))
    except DeepSeekUnavailableError:
        return []  # skip the whole batch; it'll be retried on the next run (resume support)

    category_by_name = {p["name"]: p.get("category", "amenities") for p in pois}
    all_reviews = []
    for entry in raw.get("results", []):
        name = entry.get("place_name")
        if name not in category_by_name:
            continue  # model drifted from the exact name; skip rather than guess
        for r in entry.get("reviews", []):
            if not r.get("text"):
                continue
            all_reviews.append({
                "place_name": name,
                "category": category_by_name[name],
                "text": r["text"],
                "language": r.get("language", "en"),
                "source": "synthetic_deepseek_v1",  # NEVER remove this tag
            })
    return all_reviews


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pois-path", default="data/dubai_pois.json")
    parser.add_argument("--n-pois", type=int, default=30,
                         help="How many POIs to generate reviews for (keep small — costs API calls).")
    parser.add_argument("--category", default=None,
                         choices=["safety", "quietness_positive", "quietness_negative", "amenities"],
                         help="Only generate for one category. Default: mix across all four evenly.")
    parser.add_argument("--reviews-per-poi", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=5,
                         help="How many POIs to bundle into a single API call. Higher = "
                              "fewer total requests = faster overall and fewer 429s, but "
                              "each call takes a bit longer and is more likely to time out "
                              "if set too high (try 5-8).")
    parser.add_argument("--delay-seconds", type=float, default=2.0,
                         help="Pause between batches (not between individual POIs anymore).")
    parser.add_argument("--out-path", default="data/synthetic_reviews_pois.json")
    args = parser.parse_args()

    pois = json.loads(Path(args.pois_path).read_text(encoding="utf-8"))

    # Drop POIs with no real name — nothing meaningful to review.
    pois = [p for p in pois if p.get("name") and p["name"] != "Unnamed"]

    if args.category:
        pois = [p for p in pois if p.get("category") == args.category]
        sample = pois[:args.n_pois]
    else:
        # Mix evenly across the 4 categories so we don't end up with
        # 100% "amenities" just because it's the most common in OSM data.
        by_category: dict[str, list[dict]] = {}
        for p in pois:
            by_category.setdefault(p.get("category"), []).append(p)
        per_category_n = max(1, args.n_pois // max(1, len(by_category)))
        sample = []
        for cat_pois in by_category.values():
            sample.extend(cat_pois[:per_category_n])
        sample = sample[:args.n_pois]

    out_path = Path(args.out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume support (same pattern as generate_synthetic_reviews.py):
    # skip POIs we've already generated for.
    all_reviews: list[dict] = []
    already_done: set[str] = set()
    if out_path.exists():
        all_reviews = json.loads(out_path.read_text(encoding="utf-8"))
        already_done = {r["place_name"] for r in all_reviews}
        if already_done:
            print(f"Resuming: {len(already_done)} POIs already have reviews saved, skipping them.")

    remaining = [p for p in sample if p["name"] not in already_done]
    batches = [remaining[i:i + args.batch_size] for i in range(0, len(remaining), args.batch_size)]

    print(f"{len(remaining)} POIs remaining, grouped into {len(batches)} batch(es) "
          f"of up to {args.batch_size} places each.")

    for i, batch in enumerate(batches, start=1):
        names_preview = ", ".join(p["name"] for p in batch[:3])
        suffix = "..." if len(batch) > 3 else ""
        print(f"[batch {i}/{len(batches)}] ({len(batch)} places: {names_preview}{suffix})")

        reviews = generate_for_poi_batch(batch, args.reviews_per_poi)
        all_reviews.extend(reviews)
        if not reviews:
            print("  -> skipped (rate-limited even after retries)")
        else:
            got_names = {r["place_name"] for r in reviews}
            missing = [p["name"] for p in batch if p["name"] not in got_names]
            if missing:
                print(f"  -> partial: model skipped {len(missing)} place(s) in this batch "
                      f"(will retry next run): {missing}")
            out_path.write_text(json.dumps(all_reviews, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(args.delay_seconds)

    out_path.write_text(json.dumps(all_reviews, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nDone — {len(all_reviews)} synthetic reviews saved to {out_path}")
    print("Reminder: these are SYNTHETIC (DeepSeek-generated) reviews for MVP/demo "
          "purposes only. Document this as a project Limitation.")


if __name__ == "__main__":
    main()