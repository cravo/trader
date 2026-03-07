from __future__ import annotations

from typing import Iterable
import time

import pandas as pd
import yfinance as yf


def _chunked(seq: list[str], size: int) -> list[list[str]]:
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def _empty_history_frame() -> pd.DataFrame:
    return pd.DataFrame()


def _download_chunk(
    tickers: list[str],
    period: str,
    timeout_seconds: int,
) -> pd.DataFrame:
    if not tickers:
        return _empty_history_frame()

    data = yf.download(
        tickers=tickers,
        period=period,
        interval="1d",
        auto_adjust=True,
        actions=False,
        threads=False,          # safer when we're already chunking
        group_by="ticker",
        progress=False,
        timeout=timeout_seconds,
        multi_level_index=True,
    )

    if data is None:
        return _empty_history_frame()

    if isinstance(data, pd.DataFrame) and not data.empty:
        return data

    return _empty_history_frame()


def download_price_history(
    tickers: Iterable[str],
    period: str = "6mo",
    chunk_size: int = 50,
    sleep_seconds: float = 1.0,
    retries: int = 3,
    timeout_seconds: int = 30,
) -> pd.DataFrame:
    tickers = [str(t).strip() for t in dict.fromkeys(tickers) if str(t).strip()]
    if not tickers:
        raise ValueError("No tickers supplied")

    chunks = _chunked(tickers, chunk_size)
    frames: list[pd.DataFrame] = []

    for chunk_index, chunk in enumerate(chunks, start=1):
        last_error: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                print(
                    f"Downloading chunk {chunk_index}/{len(chunks)} "
                    f"({len(chunk)} tickers), attempt {attempt}/{retries}..."
                )

                frame = _download_chunk(
                    tickers=chunk,
                    period=period,
                    timeout_seconds=timeout_seconds,
                )

                if not frame.empty:
                    frames.append(frame)

                last_error = None
                break

            except Exception as exc:
                last_error = exc
                wait_time = sleep_seconds * attempt
                print(
                    f"Chunk {chunk_index} failed on attempt {attempt}/{retries}: {exc}. "
                    f"Waiting {wait_time:.1f}s before retry..."
                )
                time.sleep(wait_time)

        if last_error is not None:
            print(
                f"Skipping chunk {chunk_index}/{len(chunks)} after {retries} failed attempts: "
                f"{last_error}"
            )

        if chunk_index < len(chunks):
            time.sleep(sleep_seconds)

    if not frames:
        raise RuntimeError("No market data returned for any chunk")

    history = pd.concat(frames, axis=1)

    if isinstance(history.columns, pd.MultiIndex):
        history = history.loc[:, ~history.columns.duplicated()]
        history = history.sort_index(axis=1)

    return history


def extract_ticker_frame(history: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame()

    if isinstance(history.columns, pd.MultiIndex):
        level0 = history.columns.get_level_values(0)
        if ticker not in level0:
            return pd.DataFrame()

        frame = history[ticker].copy()
    else:
        frame = history.copy()

    frame = frame.dropna(how="all")

    # Normalise any accidental multi-index leftovers
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(-1)

    expected_order = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in frame.columns]
    if expected_order:
        frame = frame.reindex(columns=expected_order)

    return frame