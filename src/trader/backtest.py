from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from .config import Settings
from .market_data import extract_ticker_frame
from .scoring import score_candidates
from .trade_rules import choose_trade
from .universe import UniverseMember


@dataclass
class BacktestTrade:
    signal_date: str
    ticker: str
    regime_state: str
    entry_price: float
    target_price: float
    stop_price: float
    exit_price: float
    return_pct: float
    exit_reason: str


def _market_regime_status_for_date(
    history_until_date: pd.DataFrame,
    ticker: str,
    ma20_days: int,
    ma50_days: int,
) -> str:
    frame = extract_ticker_frame(history_until_date, ticker)
    if frame.empty or "Close" not in frame.columns:
        return "unknown"

    close = frame["Close"].dropna()
    if len(close) < max(ma20_days, ma50_days):
        return "unknown"

    latest = float(close.iloc[-1])
    ma20 = float(close.rolling(ma20_days).mean().iloc[-1])
    ma50 = float(close.rolling(ma50_days).mean().iloc[-1])

    if latest > ma20:
        return "bullish"
    if latest > ma50:
        return "neutral"
    return "bearish"


def _pick_target_profit_pct(regime_state: str, settings: Settings) -> float:
    target_profit_pct = settings.target_profit_pct
    if regime_state == "neutral":
        target_profit_pct = settings.neutral_target_profit_pct
    elif regime_state == "bearish":
        target_profit_pct = settings.bearish_target_profit_pct
    return target_profit_pct


def _evaluate_forward_trade(
    full_history: pd.DataFrame,
    ticker: str,
    signal_date: pd.Timestamp,
    entry_price: float,
    target_price: float,
    stop_price: float,
    horizon_days: int,
) -> tuple[float, float, str] | None:
    frame = extract_ticker_frame(full_history, ticker)
    if frame.empty or "Close" not in frame.columns:
        return None

    future = frame[frame.index > signal_date].head(horizon_days)
    if future.empty:
        return None

    for _, row in future.iterrows():
        high_val = float(row["High"]) if "High" in row and pd.notna(row["High"]) else float(row["Close"])
        low_val = float(row["Low"]) if "Low" in row and pd.notna(row["Low"]) else float(row["Close"])

        # Conservative assumption on same-day double-hit: stop takes precedence.
        if low_val <= stop_price:
            exit_price = stop_price
            ret = ((exit_price / entry_price) - 1.0) * 100.0
            return exit_price, ret, "stop"

        if high_val >= target_price:
            exit_price = target_price
            ret = ((exit_price / entry_price) - 1.0) * 100.0
            return exit_price, ret, "target"

    exit_price = float(future["Close"].iloc[-1])
    ret = ((exit_price / entry_price) - 1.0) * 100.0
    return exit_price, ret, "timeout"


def run_backtest(
    history: pd.DataFrame,
    universe_members: Iterable[UniverseMember],
    settings: Settings,
    horizon_days: int = 5,
    max_days: int = 120,
    step_days: int = 5,
) -> tuple[list[BacktestTrade], dict]:
    if history.empty:
        return [], {"error": "empty history"}

    all_dates = list(history.index)
    if len(all_dates) < 120:
        return [], {"error": "insufficient history"}

    start_index = max(60, len(all_dates) - max_days)
    signal_dates = all_dates[start_index:]
    if step_days > 1:
        signal_dates = signal_dates[::step_days]

    trades: list[BacktestTrade] = []

    by_regime: dict[str, dict[str, float]] = {
        "bullish": {"n": 0.0, "sum_ret": 0.0, "targets": 0.0, "stops": 0.0},
        "neutral": {"n": 0.0, "sum_ret": 0.0, "targets": 0.0, "stops": 0.0},
        "bearish": {"n": 0.0, "sum_ret": 0.0, "targets": 0.0, "stops": 0.0},
        "unknown": {"n": 0.0, "sum_ret": 0.0, "targets": 0.0, "stops": 0.0},
    }

    total_signals = 0
    no_trade_signals = 0

    for signal_date in signal_dates:
        history_until_date = history.loc[:signal_date]
        regime_state = _market_regime_status_for_date(
            history_until_date=history_until_date,
            ticker=settings.market_regime_ticker,
            ma20_days=settings.market_regime_fast_ma,
            ma50_days=settings.market_regime_slow_ma,
        )

        candidates = score_candidates(
            history=history_until_date,
            universe_members=universe_members,
            settings=settings,
        )

        effective_regime_state = regime_state if settings.market_regime_filter else "bullish"
        decision = choose_trade(
            history=history_until_date,
            candidates=candidates,
            settings=settings,
            regime_state=effective_regime_state,
        )

        total_signals += 1

        if not decision.should_trade or decision.winner is None:
            no_trade_signals += 1
            continue

        winner = decision.winner
        entry_price = winner.latest_close
        target_profit_pct = _pick_target_profit_pct(regime_state, settings)
        target_price = entry_price * (1.0 + target_profit_pct / 100.0)
        stop_price = entry_price * (1.0 - settings.stop_loss_pct / 100.0)

        outcome = _evaluate_forward_trade(
            full_history=history,
            ticker=winner.ticker,
            signal_date=signal_date,
            entry_price=entry_price,
            target_price=target_price,
            stop_price=stop_price,
            horizon_days=horizon_days,
        )
        if outcome is None:
            continue

        exit_price, return_pct, exit_reason = outcome

        trades.append(
            BacktestTrade(
                signal_date=signal_date.strftime("%Y-%m-%d"),
                ticker=winner.ticker,
                regime_state=regime_state,
                entry_price=entry_price,
                target_price=target_price,
                stop_price=stop_price,
                exit_price=exit_price,
                return_pct=return_pct,
                exit_reason=exit_reason,
            )
        )

        bucket = by_regime.get(regime_state, by_regime["unknown"])
        bucket["n"] += 1
        bucket["sum_ret"] += return_pct
        if exit_reason == "target":
            bucket["targets"] += 1
        if exit_reason == "stop":
            bucket["stops"] += 1

    trade_count = len(trades)
    avg_return = (sum(t.return_pct for t in trades) / trade_count) if trade_count else 0.0
    target_hits = sum(1 for t in trades if t.exit_reason == "target")
    stop_hits = sum(1 for t in trades if t.exit_reason == "stop")

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "signals_considered": total_signals,
        "no_trade_signals": no_trade_signals,
        "trade_count": trade_count,
        "trade_rate_pct": ((trade_count / total_signals) * 100.0) if total_signals else 0.0,
        "avg_return_pct": avg_return,
        "target_hit_pct": ((target_hits / trade_count) * 100.0) if trade_count else 0.0,
        "stop_hit_pct": ((stop_hits / trade_count) * 100.0) if trade_count else 0.0,
        "by_regime": {},
    }

    regime_summary: dict[str, dict[str, float]] = {}
    for regime_name, values in by_regime.items():
        n = values["n"]
        regime_summary[regime_name] = {
            "trade_count": n,
            "avg_return_pct": (values["sum_ret"] / n) if n else 0.0,
            "target_hit_pct": ((values["targets"] / n) * 100.0) if n else 0.0,
            "stop_hit_pct": ((values["stops"] / n) * 100.0) if n else 0.0,
        }

    summary["by_regime"] = regime_summary
    return trades, summary
