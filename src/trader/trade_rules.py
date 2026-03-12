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
    regime_state: str,
) -> TradeDecision:
    working = list(candidates)

    # Adaptive thresholds by market regime.
    if regime_state == "bullish":
        rs_percent = settings.rs_universe_percent if settings.use_rs_universe_filter else 100.0
        min_weekly_change_pct = settings.min_weekly_change_pct
        min_relative_strength_pct = settings.min_relative_strength_pct
        min_volume_ratio = settings.min_volume_ratio
        require_breakout = settings.require_breakout

    elif regime_state == "neutral":
        rs_percent = min(
            getattr(settings, "neutral_rs_universe_percent", 15.0),
            settings.rs_universe_percent if settings.use_rs_universe_filter else 100.0,
        )
        min_weekly_change_pct = max(settings.min_weekly_change_pct, getattr(settings, "neutral_min_weekly_change_pct", 0.5))
        min_relative_strength_pct = max(settings.min_relative_strength_pct, getattr(settings, "neutral_min_relative_strength_pct", 1.0))
        min_volume_ratio = max(settings.min_volume_ratio, getattr(settings, "neutral_min_volume_ratio", 1.4))
        require_breakout = getattr(settings, "neutral_require_breakout", True)

    elif regime_state == "bearish":
        rs_percent = min(
            getattr(settings, "bearish_rs_universe_percent", 10.0),
            settings.rs_universe_percent if settings.use_rs_universe_filter else 100.0,
        )
        min_weekly_change_pct = max(settings.min_weekly_change_pct, getattr(settings, "bearish_min_weekly_change_pct", 1.0))
        min_relative_strength_pct = max(settings.min_relative_strength_pct, getattr(settings, "bearish_min_relative_strength_pct", 2.0))
        min_volume_ratio = max(settings.min_volume_ratio, getattr(settings, "bearish_min_volume_ratio", 1.6))
        require_breakout = getattr(settings, "bearish_require_breakout", True)

    else:
        return TradeDecision(
            should_trade=False,
            reason=f"Unknown market regime: {regime_state}",
            winner=None,
        )

    if settings.use_rs_universe_filter:
        working = filter_top_relative_strength(
            candidates=working,
            percent=rs_percent,
        )

        if not working:
            return TradeDecision(
                should_trade=False,
                reason=f"No candidates remained after relative strength universe filter in {regime_state} regime",
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

        if c.weekly_change_pct <= min_weekly_change_pct:
            continue
        if c.relative_strength_pct <= min_relative_strength_pct:
            continue
        if c.volume_ratio < min_volume_ratio:
            continue
        if require_breakout and c.breakout_flag != 1:
            continue
        if settings.use_trend_filter and not c.trend_ok:
            continue

        filtered.append(c)

    if not filtered:
        return TradeDecision(
            should_trade=False,
            reason=(
                f"No candidate passed the filters for {regime_state} regime "
                f"(RS top {rs_percent:.0f}%, min weekly {min_weekly_change_pct:.2f}%, "
                f"min RS {min_relative_strength_pct:.2f}%, min volume {min_volume_ratio:.2f}x, "
                f"breakout required={require_breakout})"
            ),
            winner=None,
        )

    filtered.sort(key=lambda c: c.score, reverse=True)

    return TradeDecision(
        should_trade=True,
        reason=f"Trade approved in {regime_state} regime",
        winner=filtered[0],
    )