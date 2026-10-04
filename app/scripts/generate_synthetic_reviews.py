"""
Generates synthetic-but-realistic reviews for real Dubai restaurant names
(pulled from data/raw/Tripadvisor_Duvai_Resturant_N.csv), using DeepSeek.

WHY THIS EXISTS:
The TripAdvisor CSV we have only contains restaurant names + links to
review pages — not the review text itself. Scraping TripAdvisor's pages
directly would likely violate their robots.txt/ToS, and no open, real,
review-text dataset with solid Dubai coverage was found (Yelp Open
Dataset barely covers the UAE).

So — mirroring exactly what the SRS itself already does with the seeded
Yelp dataset (Limitations 1.4: "Static/seeded review data") — we generate
realistic synthetic reviews for the MVP/demo only. This is clearly
labelled everywhere (source="synthetic_deepseek_v1") so it's never
confused with real user data, and must be called out as a Limitation in
the project report.

Usage:
    py -m app.scripts.generate_synthetic_reviews --n-restaurants 30 --reviews-per-restaurant 4
"""

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from app.deepseek_client import DeepSeekUnavailableError, call_json

SYSTEM_PROMPT = """You are generating realistic-sounding customer reviews for a
restaurant in Dubai, for a student software project's demo dataset (NOT real
user data — this will be clearly labeled as synthetic).

Given a restaurant name and food type, write a set of short reviews as a
regular customer would. Vary sentiment (some positive, some mixed, one
critical) and vary which aspects each review focuses on: food quality,
noise/atmosphere ("quietness"), safety/cleanliness, and nearby
amenities/convenience. Write some reviews in English and some in Arabic,
mixed naturally. Keep each review 1-3 sentences, realistic in tone, not
exaggerated.

Return ONLY a JSON object:
{
  "reviews": [
    {"text": "...", "language": "en" or "ar"},
    ...
  ]
}
"""


def build_user_prompt(name: str, food_type: str, count: int) -> str:
    return (
        f"Restaurant name: {name}\n"
        f"Food type: {food_type or 'Unknown'}\n"
        f"Generate exactly {count} reviews."
    )


def generate_for_restaurant(name: str, food_type: str, count: int) -> list[dict]:
    try:
        raw = call_json(SYSTEM_PROMPT, build_user_prompt(name, food_type, count))
    except DeepSeekUnavailableError:
        return []  # skip this restaurant rather than crash the whole batch

    reviews = raw.get("reviews", [])
    return [
        {
            "restaurant_name": name,
            "food_type": food_type,
            "text": r.get("text", ""),
            "language": r.get("language", "en"),
            "source": "synthetic_deepseek_v1",  # NEVER remove this tag
        }
        for r in reviews
        if r.get("text")
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-path", default="data/raw/Tripadvisor_Duvai_Resturant_N.csv")
    parser.add_argument("--n-restaurants", type=int, default=30,
                         help="How many restaurants to generate reviews for (keep small — costs API calls).")
    parser.add_argument("--reviews-per-restaurant", type=int, default=4)
    parser.add_argument("--delay-seconds", type=float, default=1.5,
                         help="Pause between restaurants. Raise this (e.g. to 3-5) if you're "
                              "hitting heavy 429 rate-limiting on a busy free model.")
    parser.add_argument("--out-path", default="data/synthetic_reviews.json")
    args = parser.parse_args()

    df = pd.read_csv(args.csv_path)
    # Clean known noise patterns in the raw restaurant names:
    # "Sponsored\nName" -> "Name", and "1. Name" -> "Name".
    df["Resturent_Name"] = (
        df["Resturent_Name"].astype(str)
        .str.replace(r"^Sponsored\n", "", regex=True)
        .str.replace(r"^\d+\.\s*", "", regex=True)
        .str.strip()
    )

    out_path = Path(args.out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume support: if we already have reviews saved (e.g. a previous
    # run got partially rate-limited), don't burn API calls re-doing
    # restaurants we already succeeded on.
    all_reviews: list[dict] = []
    already_done: set[str] = set()
    if out_path.exists():
        all_reviews = json.loads(out_path.read_text(encoding="utf-8"))
        already_done = {r["restaurant_name"] for r in all_reviews}
        if already_done:
            print(f"Resuming: {len(already_done)} restaurants already have reviews saved, skipping them.")

    sample = df.head(args.n_restaurants)
    remaining = sample[~sample["Resturent_Name"].isin(already_done)]

    for i, row in enumerate(remaining.itertuples(), start=1):
        name = getattr(row, "Resturent_Name")
        food_type = getattr(row, "Food_Type", None)
        print(f"[{i}/{len(remaining)}] Generating reviews for: {name}")

        reviews = generate_for_restaurant(name, food_type, args.reviews_per_restaurant)
        all_reviews.extend(reviews)
        if not reviews:
            print(f"  -> skipped (rate-limited even after retries)")
        else:
            # Save after every success so progress is never lost to a
            # crash or a later restaurant's failure.
            out_path.write_text(json.dumps(all_reviews, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(args.delay_seconds)

    out_path.write_text(json.dumps(all_reviews, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nDone — {len(all_reviews)} synthetic reviews saved to {out_path}")
    print("Reminder: these are SYNTHETIC (DeepSeek-generated) reviews for MVP/demo "
          "purposes only. Document this as a project Limitation.")


if __name__ == "__main__":
    main()