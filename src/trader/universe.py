from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import pandas as pd
import os
from pathlib import Path

@dataclass(frozen=True)
class UniverseMember:
    symbol_raw: str
    ticker_yahoo: str
    name: str
    index_name: str
    market: str


def uk_symbol_to_yahoo(symbol: str) -> str:
    cleaned = symbol.strip().upper().replace(".", "-")
    if not cleaned.endswith(".L"):
        cleaned = f"{cleaned}.L"
    return cleaned


def us_symbol_to_yahoo(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def symbol_to_yahoo(symbol: str, market: str) -> str:
    if market.upper() == "UK":
        return uk_symbol_to_yahoo(symbol)
    if market.upper() == "US":
        return us_symbol_to_yahoo(symbol)
    raise ValueError(f"Unsupported market: {market}")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _universe_dir() -> Path:
    # Allow override via environment variable
    env_path = os.getenv("UNIVERSE_PATH")
    if env_path:
        return Path(env_path)

    # Docker default
    docker_path = Path("/data/universe")
    if docker_path.exists():
        return docker_path

    # Local development fallback
    return _project_root() / "data" / "universe"


def _load_csv(filename: str) -> list[UniverseMember]:
    path = _universe_dir() / filename
    if not path.exists():
        raise FileNotFoundError(f"Universe file not found: {path}")

    df = pd.read_csv(path)

    required = {"symbol", "name", "index_name", "market"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"{path} is missing columns: {sorted(missing)}")

    members: list[UniverseMember] = []

    for _, row in df.iterrows():
        symbol = str(row["symbol"]).strip()
        name = str(row["name"]).strip()
        index_name = str(row["index_name"]).strip()
        market = str(row["market"]).strip().upper()

        if not symbol or symbol.lower() == "nan":
            continue
        if not name or name.lower() == "nan":
            continue

        members.append(
            UniverseMember(
                symbol_raw=symbol,
                ticker_yahoo=symbol_to_yahoo(symbol, market),
                name=name,
                index_name=index_name,
                market=market,
            )
        )

    return members


def fetch_ftse100_members() -> list[UniverseMember]:
    return _load_csv("ftse100.csv")


def fetch_ftse250_members() -> list[UniverseMember]:
    return _load_csv("ftse250.csv")


def fetch_sp500_members() -> list[UniverseMember]:
    return _load_csv("sp500.csv")


def fetch_nasdaq100_members() -> list[UniverseMember]:
    return _load_csv("nasdaq100.csv")


def build_universe(
    include_ftse100: bool = True,
    include_ftse250: bool = True,
    include_sp500: bool = True,
    include_nasdaq100: bool = True,
) -> List[UniverseMember]:
    members: list[UniverseMember] = []

    if include_ftse100:
        members.extend(fetch_ftse100_members())

    if include_ftse250:
        members.extend(fetch_ftse250_members())

    if include_sp500:
        members.extend(fetch_sp500_members())

    if include_nasdaq100:
        members.extend(fetch_nasdaq100_members())

    deduped: dict[str, UniverseMember] = {}
    for member in members:
        deduped.setdefault(member.ticker_yahoo, member)

    return sorted(deduped.values(), key=lambda m: (m.market, m.index_name, m.ticker_yahoo))