from __future__ import annotations

import argparse
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from trader import cli, notifier
from trader.scoring import ScoredCandidate
from trader.trade_rules import TradeDecision
from trader.universe import UniverseMember


def make_candidate(ticker: str = "AAPL") -> ScoredCandidate:
    return ScoredCandidate(
        ticker=ticker,
        name="Apple Inc",
        index_name="S&P 500",
        market="US",
        benchmark_ticker="^GSPC",
        latest_close=100.0,
        weekly_change_pct=2.5,
        monthly_change_pct=6.0,
        benchmark_5d_return_pct=1.0,
        relative_strength_pct=1.5,
        volume_ratio=1.8,
        breakout_flag=1,
        trend_ok=True,
        score=9.75,
        atr_value=2.0,
        atr_pct=2.0,
        close_position=0.8,
        distance_to_high=0.01,
    )


class NotifierAndCliTests(unittest.TestCase):
    def test_build_trade_webhook_payload_uses_passed_target_and_stop(self) -> None:
        winner = make_candidate()
        top = [winner, make_candidate("MSFT")]

        payload = notifier.build_trade_webhook_payload(
            candidate=winner,
            top_candidates=top,
            settings=SimpleNamespace(webhook_username="Trader"),
            target_price=106.25,
            stop_price=97.0,
        )

        self.assertEqual(payload["username"], "Trader")
        description = payload["embeds"][0]["description"]
        self.assertIn("**Target:** $106.25", description)
        self.assertIn("**Stop:** $97.00", description)
        self.assertIn("1. AAPL  score 9.75", description)

    @patch("trader.cli.send_trade_webhook")
    @patch("trader.cli.save_pick")
    @patch("trader.cli.save_scan_candidates")
    @patch("trader.cli.save_scan_run", return_value=123)
    @patch("trader.cli.choose_trade")
    @patch("trader.cli.score_candidates")
    @patch("trader.cli.market_regime_status", return_value=("bullish", 5000.0, 4990.0, 4950.0))
    @patch("trader.cli.download_price_history", return_value="history")
    @patch("trader.cli.build_universe")
    @patch("trader.cli.Settings")
    def test_run_pick_notifies_with_computed_prices(
        self,
        settings_cls,
        build_universe,
        _download_price_history,
        _market_regime_status,
        score_candidates,
        choose_trade,
        _save_scan_run,
        _save_scan_candidates,
        _save_pick,
        send_trade_webhook,
    ) -> None:
        winner = make_candidate()

        build_universe.return_value = [
            UniverseMember(
                symbol_raw="AAPL",
                ticker_yahoo="AAPL",
                name="Apple Inc",
                index_name="S&P 500",
                market="US",
            )
        ]
        score_candidates.return_value = [winner]
        choose_trade.return_value = TradeDecision(
            should_trade=True,
            reason="ok",
            winner=winner,
        )

        settings_cls.return_value = SimpleNamespace(
            include_ftse100=False,
            include_ftse250=False,
            include_sp500=True,
            include_nasdaq100=False,
            uk_benchmark_ticker="^FTSE",
            us_benchmark_ticker="^GSPC",
            market_regime_ticker="^GSPC",
            lookback_period="6mo",
            rs_universe_percent=20.0,
            use_rs_universe_filter=False,
            market_regime_filter=True,
            database_path=":memory:",
            dry_run=False,
            max_candidates=25,
            target_profit_pct=5.0,
            neutral_target_profit_pct=4.5,
            bearish_target_profit_pct=4.0,
            stop_loss_pct=3.0,
            market_regime_fast_ma=20,
            market_regime_slow_ma=50,
        )

        args = argparse.Namespace(command="pick", notify=True, dry_run=False, top=5)
        result = cli.run_pick(args)

        self.assertEqual(result, 0)
        send_trade_webhook.assert_called_once()

        kwargs = send_trade_webhook.call_args.kwargs
        self.assertIs(kwargs["candidate"], winner)
        self.assertAlmostEqual(kwargs["target_price"], 105.0)
        self.assertAlmostEqual(kwargs["stop_price"], 97.0)


if __name__ == "__main__":
    unittest.main()
