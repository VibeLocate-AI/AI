"""
Prepares a clean, validated handoff package of the Dubai POI data for the
backend team. Run this on your machine, where the real dubai_pois.json
(from fetch_dubai_pois.py) actually lives.

What it does:
1. Validates every entry has the required fields and a known category.
2. Drops entries with no real name ("Unnamed") — nothing useful to hand off.
3. Writes a manifest.json with counts per category + generation timestamp,
   so the backend team knows exactly what they're getting without opening
   6,000+ lines of JSON.
4. Zips everything (cleaned data + manifest + this handoff's README) into
   one file ready to send.

Usage:
    py -m app.scripts.prepare_handoff --pois-path data/dubai_pois.json
"""

import argparse
import json
import shutil
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

VALID_CATEGORIES = {"safety", "quietness_positive", "quietness_negative", "amenities"}
REQUIRED_FIELDS = {"osm_id", "name", "category", "latitude", "longitude"}


def validate_and_clean(pois: list[dict]) -> tuple[list[dict], list[str]]:
    """Returns (cleaned_pois, warnings). Never silently drops bad data —
    every removal is reported so the backend team (and you) know exactly
    what didn't make it into the handoff and why."""
    warnings = []
    cleaned = []

    for i, poi in enumerate(pois):
        missing = REQUIRED_FIELDS - poi.keys()
        if missing:
            warnings.append(f"Entry #{i} missing fields {missing} — skipped.")
            continue
        if poi["category"] not in VALID_CATEGORIES:
            warnings.append(f"Entry #{i} ('{poi.get('name')}') has unknown "
                             f"category '{poi['category']}' — skipped.")
            continue
        if not poi["name"] or poi["name"] == "Unnamed":
            continue  # expected/common, not worth a warning line each time
        cleaned.append(poi)

    return cleaned, warnings


def build_manifest(cleaned: list[dict], warnings: list[str], source_path: str) -> dict:
    counts = Counter(p["category"] for p in cleaned)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": source_path,
        "source_dataset": "OpenStreetMap (via Overpass API)",
        "license": "ODbL — attribution required for public use",
        "total_pois": len(cleaned),
        "counts_by_category": dict(counts),
        "validation_warnings_count": len(warnings),
        "schema": {
            "osm_id": "integer — unique key, use to prevent duplicate imports",
            "name": "string",
            "category": "one of: safety, quietness_positive, quietness_negative, amenities",
            "latitude": "float (WGS84)",
            "longitude": "float (WGS84)",
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pois-path", default="data/dubai_pois.json")
    parser.add_argument("--readme-path", default="HANDOFF_README.md",
                         help="Path to the handoff README to bundle alongside the data.")
    parser.add_argument("--out-dir", default="handoff")
    args = parser.parse_args()

    pois_path = Path(args.pois_path)
    if not pois_path.exists():
        print(f"ERROR: {pois_path} not found. Run fetch_dubai_pois.py first.")
        return

    raw_pois = json.loads(pois_path.read_text(encoding="utf-8"))
    cleaned, warnings = validate_and_clean(raw_pois)
    manifest = build_manifest(cleaned, warnings, str(pois_path))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "dubai_pois.json").write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if warnings:
        (out_dir / "validation_warnings.txt").write_text("\n".join(warnings), encoding="utf-8")

    readme_src = Path(args.readme_path)
    if readme_src.exists():
        shutil.copy(readme_src, out_dir / "HANDOFF_README.md")
    else:
        print(f"WARNING: {readme_src} not found — handoff will ship without the README. "
              f"Make sure to include it manually.")

    zip_path = Path(f"{args.out_dir}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in out_dir.iterdir():
            zf.write(f, arcname=f.name)

    print(f"\n=== Handoff package ready: {zip_path} ===")
    print(f"Total valid POIs: {len(cleaned)}")
    print(f"By category: {dict(manifest['counts_by_category'])}")
    if warnings:
        print(f"⚠ {len(warnings)} entries were skipped — see validation_warnings.txt")
    print(f"\nSend {zip_path} to the backend team.")


if __name__ == "__main__":
    main()
