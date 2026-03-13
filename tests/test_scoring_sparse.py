from __future__ import annotations

import unittest

import pandas as pd

from trader.config import Settings
from trader.scoring import score_candidates
from trader.universe import UniverseMember


def _mk_ticker_frame(ticker: str, rows: int, include_low: bool = True) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=rows, freq="D")
    base = {
        (ticker, "Close"): [100.0 + i for i in range(rows)],
        (ticker, "High"): [101.0 + i for i in range(rows)],
        (ticker, "Volume"): [1_500_000.0 for _ in range(rows)],
    }
    if include_low:
        base[(ticker, "Low")] = [99.0 + i for i in range(rows)]

    frame = pd.DataFrame(base, index=index)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)
    return frame


class ScoringSparseDataTests(unittest.TestCase):
    def test_sparse_candidate_data_is_skipped_without_exception(self) -> None:
        settings = Settings()

        # Benchmarks need enough bars for 5-day return calculation.
        benchmark_uk = _mk_ticker_frame(settings.uk_benchmark_ticker, rows=10)
        benchmark_us = _mk_ticker_frame(settings.us_benchmark_ticker, rows=10)

        # Candidate intentionally has too little data for min-needed windows.
        candidate = _mk_ticker_frame("AAPL", rows=10)

        history = pd.concat([benchmark_uk, benchmark_us, candidate], axis=1)

        members = [
            UniverseMember(
                symbol_raw="AAPL",
                ticker_yahoo="AAPL",
                name="Apple Inc",
                index_name="S&P 500",
                market="US",
            )
        ]

        scored = score_candidates(history=history, universe_members=members, settings=settings)
        self.assertEqual(scored, [])


if __name__ == "__main__":
    unittest.main()
