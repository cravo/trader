from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, jsonify

from .config import Settings
from .market_data import download_price_history, extract_ticker_frame
from .scoring import score_candidates
from .trade_rules import choose_trade
from .universe import build_universe


app = Flask(__name__)
settings = Settings()


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    return conn

def get_latest_scan_run() -> dict | None:
    conn = get_db_connection()

    row = conn.execute(
        """
        SELECT *
        FROM scan_runs
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    conn.close()

    return dict(row) if row else None


def parse_iso_utc(value: str) -> datetime:
    # Handles timestamps saved via datetime.now(timezone.utc).isoformat()
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def market_is_bullish(history, ticker: str, ma_days: int) -> tuple[bool, float | None, float | None]:
    frame = extract_ticker_frame(history, ticker)
    if frame.empty or "Close" not in frame.columns:
        return False, None, None

    close = frame["Close"].dropna()
    if len(close) < ma_days:
        return False, None, None

    latest = float(close.iloc[-1])
    ma = float(close.rolling(ma_days).mean().iloc[-1])
    return latest > ma, latest, ma

def load_dashboard_data() -> dict:
    conn = get_db_connection()

    latest_run = conn.execute(
        """
        SELECT *
        FROM scan_runs
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    if latest_run is None:
        conn.close()
        return {
            "run": None,
            "candidates": [],
            "picks": [],
        }

    candidates = conn.execute(
        """
        SELECT *
        FROM scan_candidates
        WHERE scan_run_id = ?
        ORDER BY rank ASC
        """,
        (latest_run["id"],),
    ).fetchall()

    picks = conn.execute(
        """
        SELECT *
        FROM picks
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()

    conn.close()

    return {
        "run": dict(latest_run),
        "candidates": [dict(row) for row in candidates],
        "picks": [dict(row) for row in picks],
    }

def build_dashboard_data() -> dict:
    universe_members = build_universe(
        include_ftse100=settings.include_ftse100,
        include_ftse250=settings.include_ftse250,
        include_sp500=settings.include_sp500,
        include_nasdaq100=settings.include_nasdaq100,
    )

    tickers = [m.ticker_yahoo for m in universe_members]
    benchmarks = [settings.uk_benchmark_ticker, settings.us_benchmark_ticker]
    all_tickers = list(dict.fromkeys(tickers + benchmarks))

    history = download_price_history(all_tickers, period=settings.lookback_period)

    candidates = score_candidates(
        history=history,
        universe_members=universe_members,
        settings=settings,
    )

    decision = choose_trade(
        history=history,
        candidates=candidates,
        settings=settings,
    )

    regime_ticker = settings.market_regime_ticker if hasattr(settings, "market_regime_ticker") else settings.us_benchmark_ticker
    regime_ma = settings.market_regime_ma if hasattr(settings, "market_regime_ma") else 50

    regime_ok, regime_latest, regime_avg = market_is_bullish(history, regime_ticker, regime_ma)

    top_candidates = []
    for c in candidates[:10]:
        top_candidates.append(
            {
                "ticker": c.ticker,
                "name": c.name,
                "market": c.market,
                "index_name": c.index_name,
                "latest_close": c.latest_close,
                "weekly_change_pct": c.weekly_change_pct,
                "monthly_change_pct": getattr(c, "monthly_change_pct", None),
                "relative_strength_pct": c.relative_strength_pct,
                "volume_ratio": c.volume_ratio,
                "breakout_flag": c.breakout_flag,
                "trend_ok": c.trend_ok,
                "score": c.score,
            }
        )

    recent_picks = load_recent_picks()

    wins = [p for p in recent_picks if p["target_price"] > p["latest_close"]]
    total = len(recent_picks)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "universe_size": len(universe_members),
        "regime": {
            "ticker": regime_ticker,
            "ma_days": regime_ma,
            "bullish": regime_ok,
            "latest": regime_latest,
            "ma": regime_avg,
        },
        "decision": {
            "should_trade": decision.should_trade,
            "reason": decision.reason,
            "winner": decision.winner,
        },
        "top_candidates": top_candidates,
        "recent_picks": recent_picks,
        "stats": {
            "recent_pick_count": total,
            "top_candidate_count": len(top_candidates),
        },
    }

@app.route("/health")
def health():
    latest = get_latest_scan_run()

    if latest is None:
        return jsonify(
            {
                "status": "unhealthy",
                "reason": "no scans found",
            }
        ), 503

    run_at = parse_iso_utc(latest["run_at_utc"])
    now = datetime.now(timezone.utc)

    # Consider the scan healthy if it ran within the last 36 hours.
    # This gives enough slack for weekday-only scheduling.
    max_age = timedelta(hours=36)
    age = now - run_at
    is_healthy = age <= max_age

    payload = {
        "status": "healthy" if is_healthy else "stale",
        "last_scan_utc": latest["run_at_utc"],
        "age_seconds": int(age.total_seconds()),
        "should_trade": bool(latest["should_trade"]),
        "regime_bullish": bool(latest["regime_bullish"]),
        "winner_ticker": latest["winner_ticker"],
    }

    return jsonify(payload), 200 if is_healthy else 503

@app.route("/")
def dashboard():
    data = load_dashboard_data()
    return render_template("dashboard.html", data=data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)