"""
Quick inspector for any raw review/restaurant CSV before we write the
real cleaning/loading logic. Run this first on whatever dataset you
download (Kaggle, etc.) so we know the exact column names, dtypes, and
a few real rows — instead of guessing and writing code that breaks on
the actual file.

Usage:
    py -m app.scripts.inspect_reviews_csv data/raw/YOUR_FILE.csv
"""

import sys
from pathlib import Path

import pandas as pd


def inspect(csv_path: str) -> None:
    path = Path(csv_path)
    if not path.exists():
        print(f"File not found: {path}")
        return

    df = pd.read_csv(path)

    print(f"=== {path.name} ===")
    print(f"Rows: {len(df)}   Columns: {len(df.columns)}\n")

    print("--- Column names & types ---")
    print(df.dtypes)

    print("\n--- First 3 rows ---")
    print(df.head(3).to_string())

    print("\n--- Missing values per column ---")
    print(df.isna().sum())

    # Try to spot which column is likely the free-text review, since
    # that's the one that matters most for Sentiment Analysis.
    text_like_cols = [
        c for c in df.columns
        if pd.api.types.is_string_dtype(df[c])
        and df[c].dropna().astype(str).str.len().mean() > 40
    ]
    if text_like_cols:
        print(f"\n--- Likely free-text review column(s): {text_like_cols} ---")
    else:
        print("\n--- No obvious long free-text column found. "
              "This dataset may only have ratings/metadata, no review text. ---")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: py -m app.scripts.inspect_reviews_csv <path_to_csv>")
        sys.exit(1)
    inspect(sys.argv[1])