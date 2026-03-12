from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value is not None else default


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value is not None else default


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "trader")
    database_path: str = os.getenv("DATABASE_PATH", "/data/momentum.db")

    uk_benchmark_ticker: str = os.getenv("UK_BENCHMARK_TICKER", "^FTSE")
    us_benchmark_ticker: str = os.getenv("US_BENCHMARK_TICKER", "^GSPC")

    starting_capital: float = _get_float("STARTING_CAPITAL", 100.0)
    target_profit_pct: float = _get_float("TARGET_PROFIT_PCT", 5.0)
    stop_loss_pct: float = _get_float("STOP_LOSS_PCT", 3.0)

    weight_weekly_change: float = _get_float("WEIGHT_WEEKLY_CHANGE", 0.35)
    weight_relative_strength: float = _get_float("WEIGHT_RELATIVE_STRENGTH", 0.30)
    weight_volume_ratio: float = _get_float("WEIGHT_VOLUME_RATIO", 0.20)
    weight_breakout: float = _get_float("WEIGHT_BREAKOUT", 0.15)
    weight_close_strength: float = _get_float("WEIGHT_CLOSE_STRENGTH", 1.0)
    weight_proximity: float = _get_float("WEIGHT_PROXIMITY", 1.0)

    include_ftse100: bool = _get_bool("INCLUDE_FTSE100", True)
    include_ftse250: bool = _get_bool("INCLUDE_FTSE250", True)
    include_sp500: bool = _get_bool("INCLUDE_SP500", True)
    include_nasdaq100: bool = _get_bool("INCLUDE_NASDAQ100", True)

    min_price_gbp: float = _get_float("MIN_PRICE_GBP", 0.50)
    min_price_usd: float = _get_float("MIN_PRICE_USD", 5.00)
    min_30d_avg_volume_uk: float = _get_float("MIN_30D_AVG_VOLUME_UK", 200000.0)
    min_30d_avg_volume_us: float = _get_float("MIN_30D_AVG_VOLUME_US", 500000.0)

    market_regime_filter: bool = _get_bool("MARKET_REGIME_FILTER", True)
    market_regime_ma: int = _get_int("MARKET_REGIME_MA", 50)
    market_regime_ticker: str = os.getenv("MARKET_REGIME_TICKER", "^GSPC")

    market_regime_fast_ma: int = _get_int("MARKET_REGIME_FAST_MA", 20)
    market_regime_slow_ma: int = _get_int("MARKET_REGIME_SLOW_MA", 50)

    use_rs_universe_filter: bool = _get_bool("USE_RS_UNIVERSE_FILTER", True)
    rs_universe_percent: float = _get_float("RS_UNIVERSE_PERCENT", 20.0)

    lookback_period: str = os.getenv("LOOKBACK_PERIOD", "6mo")
    breakout_lookback_days: int = _get_int("BREAKOUT_LOOKBACK_DAYS", 20)

    min_weekly_change_pct: float = _get_float("MIN_WEEKLY_CHANGE_PCT", 0.0)
    min_relative_strength_pct: float = _get_float("MIN_RELATIVE_STRENGTH_PCT", 0.0)
    min_volume_ratio: float = _get_float("MIN_VOLUME_RATIO", 1.2)
    require_breakout: bool = _get_bool("REQUIRE_BREAKOUT", True)
    use_benchmark_ma_filter: bool = _get_bool("USE_BENCHMARK_MA_FILTER", True)
    benchmark_ma_days: int = _get_int("BENCHMARK_MA_DAYS", 50)

    use_trend_filter: bool = _get_bool("USE_TREND_FILTER", True)
    trend_fast_ma_days: int = _get_int("TREND_FAST_MA_DAYS", 20)
    trend_slow_ma_days: int = _get_int("TREND_SLOW_MA_DAYS", 50)

    min_20d_avg_volume: float = _get_float("MIN_20D_AVG_VOLUME", 1_000_000)
    min_20d_avg_dollar_volume: float = _get_float("MIN_20D_AVG_DOLLAR_VOLUME", 50_000_000)

    neutral_target_profit_pct: float = _get_float("NEUTRAL_TARGET_PROFIT_PCT", 4.5)
    bearish_target_profit_pct: float = _get_float("BEARISH_TARGET_PROFIT_PCT", 4.0)

    neutral_rs_universe_percent: float = _get_float("NEUTRAL_RS_UNIVERSE_PERCENT", 15.0)
    bearish_rs_universe_percent: float = _get_float("BEARISH_RS_UNIVERSE_PERCENT", 10.0)

    neutral_min_weekly_change_pct: float = _get_float("NEUTRAL_MIN_WEEKLY_CHANGE_PCT", 0.5)
    bearish_min_weekly_change_pct: float = _get_float("BEARISH_MIN_WEEKLY_CHANGE_PCT", 1.0)

    neutral_min_relative_strength_pct: float = _get_float("NEUTRAL_MIN_RELATIVE_STRENGTH_PCT", 1.0)
    bearish_min_relative_strength_pct: float = _get_float("BEARISH_MIN_RELATIVE_STRENGTH_PCT", 2.0)

    neutral_min_volume_ratio: float = _get_float("NEUTRAL_MIN_VOLUME_RATIO", 1.4)
    bearish_min_volume_ratio: float = _get_float("BEARISH_MIN_VOLUME_RATIO", 1.6)

    neutral_require_breakout: bool = _get_bool("NEUTRAL_REQUIRE_BREAKOUT", True)
    bearish_require_breakout: bool = _get_bool("BEARISH_REQUIRE_BREAKOUT", True)

    webhook_url: str = os.getenv("WEBHOOK_URL", "")
    webhook_username: str = os.getenv("WEBHOOK_USERNAME", "Trader")

    max_candidates: int = _get_int("MAX_CANDIDATES", 25)
    dry_run: bool = _get_bool("DRY_RUN", False)

    def benchmark_for_market(self, market: str) -> str:
        if market.upper() == "UK":
            return self.uk_benchmark_ticker
        if market.upper() == "US":
            return self.us_benchmark_ticker
        raise ValueError(f"Unsupported market: {market}")