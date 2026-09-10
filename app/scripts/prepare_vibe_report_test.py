"""
Helper script: pulls a batch of real generated reviews from
data/synthetic_reviews_pois.json and prints a ready-to-paste JSON body
for testing POST /api/reviews/vibe-report via Swagger (/docs).

This does NOT call the AI service itself — it just prepares the request
body so you can paste it directly into Swagger's "Try it out" box.

Usage:
    py -m app.scripts.prepare_vibe_report_test
    py -m app.scripts.prepare_vibe_report_test --place "Cavalli Club"
    py -m app.scripts.prepare_vibe_report_test --category amenities --n 5
"""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviews-path", default="data/synthetic_reviews_pois.json")
    parser.add_argument("--place", default=None,
                         help="Filter to reviews for one specific place name.")
    parser.add_argument("--category", default=None,
                         choices=["safety", "quietness_positive", "quietness_negative", "amenities"],
                         help="Filter to reviews of one category instead of one place.")
    parser.add_argument("--n", type=int, default=None,
                         help="Limit to N reviews (default: all matching).")
    args = parser.parse_args()

    reviews = json.loads(Path(args.reviews_path).read_text(encoding="utf-8"))

    if args.place:
        reviews = [r for r in reviews if r["place_name"] == args.place]
    elif args.category:
        reviews = [r for r in reviews if r["category"] == args.category]

    if args.n:
        reviews = reviews[:args.n]

    if not reviews:
        print("No matching reviews found. Check --place / --category spelling, "
              "or run without filters to see everything.")
        return

    # Build the exact request body /api/reviews/vibe-report expects:
    # a plain list of {"text": ..., "source": ...} objects.
    body = [{"text": r["text"], "source": r["source"]} for r in reviews]

    print(f"=== {len(reviews)} review(s) selected ===")
    places = sorted(set(r["place_name"] for r in reviews))
    print(f"Place(s): {', '.join(places[:5])}{'...' if len(places) > 5 else ''}")
    print()
    print("=== Paste this into Swagger's Request body for POST /api/reviews/vibe-report ===")
    print(json.dumps(body, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()