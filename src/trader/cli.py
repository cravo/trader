from __future__ import annotations

import argparse

from .config import Settings
from .market_data import download_price_history
from .notifier import send_no_trade_webhook, send_trade_webhook
from .scoring import score_candidates
from .storage import save_pick, save_scan_run, save_scan_candidates
from .trade_rules import TradeDecision, choose_trade
from .universe import build_universe


def market_regime_status(
    history,
    ticker: str,
    ma20_days: int = 20,
    ma50_days: int = 50,
) -> tuple[str, float | None, float | None, float | None]:
    from .market_data import extract_ticker_frame

    frame = extract_ticker_frame(history, ticker)

    if frame.empty or "Close" not in frame.columns:
        return "unknown", None, None, None

    close = frame["Close"].dropna()

    if len(close) < max(ma20_days, ma50_days):
        return "unknown", None, None, None

    latest = float(close.iloc[-1])
    ma20 = float(close.rolling(ma20_days).mean().iloc[-1])
    ma50 = float(close.rolling(ma50_days).mean().iloc[-1])

    if latest > ma20:
        regime = "bullish"
    elif latest > ma50:
        regime = "neutral"
    else:
        regime = "bearish"

    return regime, latest, ma20, ma50


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Trader")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pick_parser = subparsers.add_parser("pick", help="Generate the trade pick")
    pick_parser.add_argument("--notify", action="store_true", help="Send webhook notification")
    pick_parser.add_argument("--dry-run", action="store_true", help="Do not persist or notify")
    pick_parser.add_argument("--top", type=int, default=10, help="Number of top candidates to print")

    return parser


def print_top_candidates(candidates, top_n: int) -> None:
    print("\nTop candidates:")
    print("-" * 150)

    for i, c in enumerate(candidates[:top_n], start=1):
        print(
            f"{i:02d}. {c.ticker:10} "
            f"{c.name[:24]:24} "
            f"{c.market:2} "
            f"5d={c.weekly_change_pct:6.2f}% "
            f"20d={c.monthly_change_pct:6.2f}% "
            f"rs={c.relative_strength_pct:6.2f}% "
            f"vol={c.volume_ratio:4.2f}x "
            f"trend={'UP' if c.trend_ok else 'DOWN'} "
            f"score={c.score:6.2f}"
        )

    print("-" * 150)


def run_pick(args: argparse.Namespace) -> int:
    settings = Settings()

    print("Building mixed UK/US universe...")
    universe_members = build_universe(
        include_ftse100=settings.include_ftse100,
        include_ftse250=settings.include_ftse250,
        include_sp500=settings.include_sp500,
        include_nasdaq100=settings.include_nasdaq100,
    )
    print(f"Universe size: {len(universe_members)}")

    tickers = [m.ticker_yahoo for m in universe_members]
    benchmarks = [
        settings.uk_benchmark_ticker,
        settings.us_benchmark_ticker,
    ]
    all_tickers = list(dict.fromkeys(tickers + benchmarks))

    print("Downloading market data...")
    history = download_price_history(all_tickers, period=settings.lookback_period)

    regime_state, regime_latest, regime_ma20, regime_ma50 = market_regime_status(
        history=history,
        ticker=settings.market_regime_ticker,
        ma20_days=getattr(settings, "market_regime_fast_ma", 20),
        ma50_days=getattr(settings, "market_regime_slow_ma", 50),
    )

    latest_str = f"{regime_latest:.2f}" if regime_latest is not None else "n/a"
    print(
        f"Market regime: {regime_state.upper()} "
        f"(ticker={settings.market_regime_ticker}, latest={latest_str})"
    )
    if regime_latest is not None and regime_ma20 is not None and regime_ma50 is not None:
        print(
            f"Regime detail: latest={regime_latest:.2f}, "
            f"ma20={regime_ma20:.2f}, ma50={regime_ma50:.2f}"
        )

    print("Scoring candidates...")
    candidates = score_candidates(
        history=history,
        universe_members=universe_members,
        settings=settings,
    )

    if not candidates:
        print("No candidates found after scoring.")
        return 1

    print_top_candidates(candidates, top_n=args.top)

    if settings.use_rs_universe_filter:
        rs_keep_count = max(1, int(len(candidates) * (settings.rs_universe_percent / 100.0)))
        print(
            f"Relative strength universe filter enabled: keeping top "
            f"{settings.rs_universe_percent:.0f}% ({rs_keep_count} of {len(candidates)}) by RS"
        )

    decision = choose_trade(
        history=history,
        candidates=candidates,
        settings=settings,
        regime_state=regime_state,
    )

    dry_run = args.dry_run or settings.dry_run

    if not dry_run:
        scan_id = save_scan_run(
            database_path=settings.database_path,
            universe_size=len(universe_members),
            regime_ticker=settings.market_regime_ticker,
            regime_state=regime_state,
            regime_price=regime_latest,
            regime_ma_fast=regime_ma20,
            regime_ma_slow=regime_ma50,
            should_trade=decision.should_trade,
            decision_reason=decision.reason,
            winner=decision.winner,
        )

        save_scan_candidates(
            database_path=settings.database_path,
            scan_id=scan_id,
            candidates=candidates,
            limit=10,
        )
        print(f"Saved scan run and candidates to SQLite with scan_id={scan_id}.")

    if not decision.should_trade:
        print("\nNo trade today.")
        print(f"Reason: {decision.reason}")

        if args.notify and not dry_run:
            send_no_trade_webhook(f"[{regime_state}] {decision.reason}", settings)
            print("No-trade webhook notification sent.")

        return 0

    winner = decision.winner
    assert winner is not None

    target_profit_pct = settings.target_profit_pct
    if regime_state == "neutral":
        target_profit_pct = getattr(settings, "neutral_target_profit_pct", target_profit_pct)
    elif regime_state == "bearish":
        target_profit_pct = getattr(settings, "bearish_target_profit_pct", target_profit_pct)

    target_price = winner.latest_close * (1.0 + target_profit_pct / 100.0)
    stop_price = winner.latest_close * (1.0 - settings.stop_loss_pct / 100.0)
    currency_symbol = "$" if winner.market == "US" else "£"

    print("\nSelected trade pick:")
    print(f"Ticker:             {winner.ticker}")
    print(f"Name:               {winner.name}")
    print(f"Market:             {winner.market}")
    print(f"Index:              {winner.index_name}")
    print(f"Benchmark:          {winner.benchmark_ticker}")
    print(f"Regime:             {regime_state.upper()}")
    print(f"Buy price:          {currency_symbol}{winner.latest_close:.2f}")
    print(f"Target (+{target_profit_pct:.1f}%): {currency_symbol}{target_price:.2f}")
    print(f"Stop (-{settings.stop_loss_pct:.1f}%):   {currency_symbol}{stop_price:.2f}")
    print(f"5D return:          {winner.weekly_change_pct:.2f}%")
    print(f"20D return:         {winner.monthly_change_pct:.2f}%")
    print(f"Relative strength:  {winner.relative_strength_pct:.2f}%")
    print(f"Volume ratio:       {winner.volume_ratio:.2f}x")
    print(f"Breakout:           {'Yes' if winner.breakout_flag else 'No'}")
    print(f"Trend filter:       {'Pass' if winner.trend_ok else 'Fail'}")
    print(f"Score:              {winner.score:.3f}")

    if dry_run:
        print("\nDry run enabled: not saving pick and not sending notifications.")
        return 0

    save_pick(
        database_path=settings.database_path,
        winner=winner,
        target=target_price,
        stop=stop_price,
    )
    print("Saved pick to SQLite.")

    if args.notify:
        send_trade_webhook(winner, candidates, settings)
        print("Trade webhook notification sent.")

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "pick":
        return run_pick(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())