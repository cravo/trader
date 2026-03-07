from __future__ import annotations

from io import StringIO
from pathlib import Path
import traceback

import pandas as pd
import requests


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "universe"

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"


def fetch_tables(url: str) -> list[pd.DataFrame]:
    print(f"Fetching: {url}")
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text))
    print(f"  Found {len(tables)} HTML tables")
    return tables


def write_csv(df: pd.DataFrame, filename: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / filename
    df.to_csv(path, index=False)
    print(f"  Wrote {len(df)} rows -> {path}")


def clean_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["symbol"] = df["symbol"].astype(str).str.strip()
    df["name"] = df["name"].astype(str).str.strip()
    df = df[df["symbol"].ne("") & df["symbol"].ne("nan")]
    df = df[df["name"].ne("") & df["name"].ne("nan")]
    df = df.drop_duplicates(subset=["symbol"])
    return df


def build_sp500() -> None:
    print("Building S&P 500 CSV...")
    tables = fetch_tables(SP500_URL)
    table = tables[0]

    df = pd.DataFrame(
        {
            "symbol": table["Symbol"],
            "name": table["Security"],
            "index_name": "S&P 500",
            "market": "US",
        }
    )
    df = clean_df(df)
    write_csv(df, "sp500.csv")


def build_nasdaq100() -> None:
    print("Building Nasdaq-100 CSV...")
    tables = fetch_tables(NASDAQ100_URL)

    target = None
    symbol_col = None
    name_col = None

    for i, table in enumerate(tables):
        cols = [str(c).strip() for c in table.columns]
        cols_lower = [c.lower() for c in cols]
        print(f"  Table {i}: columns={cols}")

        possible_symbol_cols = [c for c in table.columns if str(c).strip().lower() in {"ticker", "symbol"}]
        possible_name_cols = [c for c in table.columns if "company" in str(c).strip().lower()]

        if possible_symbol_cols and possible_name_cols:
            target = table
            symbol_col = possible_symbol_cols[0]
            name_col = possible_name_cols[0]
            break

    if target is None or symbol_col is None or name_col is None:
        raise RuntimeError("Could not locate Nasdaq-100 constituent table")

    df = pd.DataFrame(
        {
            "symbol": target[symbol_col],
            "name": target[name_col],
            "index_name": "Nasdaq-100",
            "market": "US",
        }
    )
    df = clean_df(df)
    write_csv(df, "nasdaq100.csv")


def main() -> int:
    print(f"Repo root: {ROOT}")
    print(f"Output dir: {OUT_DIR}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        build_sp500()
        build_nasdaq100()
        print("Done.")
        return 0
    except Exception as exc:
        print("\nFAILED:")
        print(exc)
        print()
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())