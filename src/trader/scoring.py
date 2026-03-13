from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .config import Settings
from .market_data import extract_ticker_frame
from .universe import UniverseMember


@dataclass
class ScoredCandidate:
    ticker: str
    name: str
    index_name: str
    market: str
    benchmark_ticker: str
    latest_close: float
    weekly_change_pct: float
    monthly_change_pct: float
    benchmark_5d_return_pct: float
    relative_strength_pct: float
    volume_ratio: float
    breakout_flag: int
    trend_ok: bool
    score: float
    atr_value: float
    atr_pct: float
    close_position: float
    distance_to_high: float

def pct_return(series: pd.Series, periods_back: int) -> float | None:
    series = series.dropna()
    if len(series) <= periods_back:
        return None

    old = float(series.iloc[-(periods_back + 1)])
    new = float(series.iloc[-1])

    if old == 0:
        return None

    return ((new / old) - 1.0) * 100.0

def compute_atr_like(high_series: pd.Series, low_series: pd.Series, close_series: pd.Series, days: int = 14) -> float | None:
    high_series = high_series.dropna()
    low_series = low_series.dropna()
    close_series = close_series.dropna()

    if len(high_series) < days + 1 or len(low_series) < days + 1 or len(close_series) < days + 1:
        return None

    prev_close = close_series.shift(1)
    tr = pd.concat(
        [
            (high_series - low_series).abs(),
            (high_series - prev_close).abs(),
            (low_series - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(days).mean().iloc[-1]
    if pd.isna(atr):
        return None

    return float(atr)

def compute_breakout_flag(close_series: pd.Series, high_series: pd.Series, lookback_days: int) -> int | None:
    close_series = close_series.dropna()
    high_series = high_series.dropna()

    if len(close_series) < lookback_days + 1 or len(high_series) < lookback_days + 1:
        return None

    latest_close = float(close_series.iloc[-1])
    prior_high = float(high_series.iloc[-(lookback_days + 1):-1].max())

    return 1 if latest_close > prior_high else 0


def compute_trend_ok(close_series: pd.Series, fast_days: int, slow_days: int) -> bool | None:

    close_series = close_series.dropna()

    required = max(fast_days, slow_days)

    if len(close_series) < required:
        return None

    fast_ma = float(close_series.rolling(fast_days).mean().iloc[-1])
    slow_ma = float(close_series.rolling(slow_days).mean().iloc[-1])
    latest_close = float(close_series.iloc[-1])

    # Strong trend conditions
    price_above_ma = latest_close > slow_ma
    fast_above_slow = fast_ma > slow_ma

    return price_above_ma and fast_above_slow


def score_candidates(
    history: pd.DataFrame,
    universe_members: Iterable[UniverseMember],
    settings: Settings,
) -> list[ScoredCandidate]:
    benchmark_returns: dict[str, float] = {}

    for market in {"UK", "US"}:
        benchmark_ticker = settings.benchmark_for_market(market)
        benchmark_frame = extract_ticker_frame(history, benchmark_ticker)
        if benchmark_frame.empty or "Close" not in benchmark_frame.columns:
            raise RuntimeError(f"No benchmark data for {benchmark_ticker}")

        benchmark_return = pct_return(benchmark_frame["Close"], periods_back=5)
        if benchmark_return is None:
            raise RuntimeError(f"Could not compute 5-day return for benchmark {benchmark_ticker}")

        benchmark_returns[market] = benchmark_return

    candidates: list[ScoredCandidate] = []

    for member in universe_members:
        frame = extract_ticker_frame(history, member.ticker_yahoo)
        if frame.empty:
            continue

        required_cols = {"Close", "High", "Low", "Volume"}
        if not required_cols.issubset(set(frame.columns)):
            continue

        close_series = frame["Close"].dropna()
        high_series = frame["High"].dropna()
        volume_series = frame["Volume"].dropna()
        low_series = frame["Low"].dropna()

        min_needed = max(
            31,
            settings.breakout_lookback_days + 1,
            settings.trend_slow_ma_days,
            20,
        )
        if (
            len(close_series) < min_needed
            or len(high_series) < min_needed
            or len(low_series) < min_needed
            or len(volume_series) < min_needed
        ):
            continue

        avg_20d_close = float(close_series.iloc[-20:].mean())
        avg_20d_volume = float(volume_series.iloc[-20:].mean())
        avg_20d_dollar_volume = avg_20d_close * avg_20d_volume

        if avg_20d_volume < settings.min_20d_avg_volume:
            continue

        if avg_20d_dollar_volume < settings.min_20d_avg_dollar_volume:
            continue

        range_today = high_series.iloc[-1] - low_series.iloc[-1]

        if range_today <= 0:
            close_position = 0.5
        else:
            close_position = (
                close_series.iloc[-1] - low_series.iloc[-1]
            ) / range_today
    
        if close_position < 0.6:
            continue

        high_20 = high_series.rolling(20).max().iloc[-1]

        if high_20 <= 0:
            continue

        latest_close = float(close_series.iloc[-1])

        distance_to_high = (high_20 - latest_close) / high_20

        if distance_to_high > 0.05:
            continue

        if member.market == "UK":
            if latest_close < settings.min_price_gbp:
                continue
            min_avg_volume = settings.min_30d_avg_volume_uk
        elif member.market == "US":
            if latest_close < settings.min_price_usd:
                continue
            min_avg_volume = settings.min_30d_avg_volume_us
        else:
            continue

        weekly_change_pct = pct_return(close_series, periods_back=5)
        if weekly_change_pct is None:
            continue

        monthly_change_pct = pct_return(close_series, periods_back=20)
        if monthly_change_pct is None:
            continue

        avg_30d_volume = float(volume_series.iloc[-31:-1].mean())
        if avg_30d_volume < min_avg_volume:
            continue

        latest_volume = float(volume_series.iloc[-1])
        if avg_30d_volume <= 0:
            continue

        volume_ratio = latest_volume / avg_30d_volume

        breakout_flag = compute_breakout_flag(
            close_series=close_series,
            high_series=high_series,
            lookback_days=settings.breakout_lookback_days,
        )
        if breakout_flag is None:
            continue

        atr_value = compute_atr_like(
            high_series=high_series,
            low_series=frame["Low"].dropna(),
            close_series=close_series,
            days=14,
        )
        if atr_value is None or latest_close <= 0:
            continue

        atr_pct = (atr_value / latest_close) * 100.0

        if atr_pct < 1.5 or atr_pct > 6.0:
            continue

        trend_ok = compute_trend_ok(
            close_series=close_series,
            fast_days=settings.trend_fast_ma_days,
            slow_days=settings.trend_slow_ma_days,
        )
        if trend_ok is None:
            continue

        benchmark_ticker = settings.benchmark_for_market(member.market)
        benchmark_5d_return_pct = benchmark_returns[member.market]
        relative_strength_pct = weekly_change_pct - benchmark_5d_return_pct

        momentum_score = (
            (weekly_change_pct * 0.6) +
            (monthly_change_pct * 0.4)
        )

        vol_adjusted_momentum = momentum_score / max(atr_pct, 0.01)

        proximity_score = max(0, 0.03 - distance_to_high)

        score = (
            vol_adjusted_momentum * settings.weight_weekly_change
            + relative_strength_pct * settings.weight_relative_strength
            + volume_ratio * settings.weight_volume_ratio
            + breakout_flag * settings.weight_breakout
            + close_position * settings.weight_close_strength
            + proximity_score * settings.weight_proximity
        )

        candidates.append(
            ScoredCandidate(
                ticker=member.ticker_yahoo,
                name=member.name,
                index_name=member.index_name,
                market=member.market,
                benchmark_ticker=benchmark_ticker,
                latest_close=latest_close,
                weekly_change_pct=weekly_change_pct,
                monthly_change_pct=monthly_change_pct,
                benchmark_5d_return_pct=benchmark_5d_return_pct,
                relative_strength_pct=relative_strength_pct,
                volume_ratio=volume_ratio,
                breakout_flag=breakout_flag,
                trend_ok=trend_ok,
                score=score,
                atr_value=atr_value,
                atr_pct=atr_pct,
                close_position=close_position,
                distance_to_high=distance_to_high,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates