from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import Settings
from .market_data import extract_ticker_frame
from .scoring import ScoredCandidate


@dataclass
class TradeDecision:
    should_trade: bool
    reason: str
    winner: ScoredCandidate | None


def benchmark_above_ma(history: pd.DataFrame, benchmark_ticker: str, ma_days: int) -> bool:
    frame = extract_ticker_frame(history, benchmark_ticker)
    if frame.empty or "Close" not in frame.columns:
        return False

    close = frame["Close"].dropna()
    if len(close) < ma_days:
        return False

    ma_value = float(close.rolling(ma_days).mean().iloc[-1])
    latest_close = float(close.iloc[-1])

    return latest_close > ma_value


def filter_top_relative_strength(
    candidates: list[ScoredCandidate],
    percent: float,
) -> list[ScoredCandidate]:
    if not candidates:
        return []

    if percent <= 0:
        return candidates

    ranked = sorted(candidates, key=lambda c: c.relative_strength_pct, reverse=True)
    keep_count = max(1, int(len(ranked) * (percent / 100.0)))
    return ranked[:keep_count]


def choose_trade(
    history: pd.DataFrame,
    candidates: list[ScoredCandidate],
    settings: Settings,
) -> TradeDecision:
    working = list(candidates)

    if settings.use_rs_universe_filter:
        working = filter_top_relative_strength(
            candidates=working,
            percent=settings.rs_universe_percent,
        )

        if not working:
            return TradeDecision(
                should_trade=False,
                reason="No candidates remained after relative strength universe filter",
                winner=None,
            )

    filtered: list[ScoredCandidate] = []

    for c in working:
        if settings.use_benchmark_ma_filter:
            if not benchmark_above_ma(
                history=history,
                benchmark_ticker=c.benchmark_ticker,
                ma_days=settings.benchmark_ma_days,
            ):
                continue

        if c.weekly_change_pct <= settings.min_weekly_change_pct:
            continue
        if c.relative_strength_pct <= settings.min_relative_strength_pct:
            continue
        if c.volume_ratio < settings.min_volume_ratio:
            continue
        if settings.require_breakout and c.breakout_flag != 1:
            continue
        if settings.use_trend_filter and not c.trend_ok:
            continue

        filtered.append(c)

    if not filtered:
        return TradeDecision(
            should_trade=False,
            reason="No candidate passed the relative strength / regime / momentum / volume / breakout / trend filters",
            winner=None,
        )

    filtered.sort(key=lambda c: c.score, reverse=True)

    return TradeDecision(
        should_trade=True,
        reason="Trade approved",
        winner=filtered[0],
    )