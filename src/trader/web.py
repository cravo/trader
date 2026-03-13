from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any

from flask import Flask, render_template, jsonify

from .config import Settings
from .market_data import download_price_history, extract_ticker_frame
from .storage import get_outcome_summary_by_horizon, get_recent_pick_outcomes


app = Flask(__name__)
settings = Settings()
PRICE_SPARKLINE_TTL = timedelta(minutes=20)
_PRICE_SPARKLINE_CACHE: dict[str, dict[str, Any]] = {}


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def parse_iso_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_age_label(age: timedelta) -> str:
    total_seconds = max(0, int(age.total_seconds()))
    if total_seconds < 60:
        return "just now"
    if total_seconds < 3600:
        return f"{total_seconds // 60}m ago"
    if total_seconds < 86400:
        return f"{total_seconds // 3600}h ago"
    return f"{total_seconds // 86400}d ago"


def _freshness_state(age: timedelta) -> str:
    if age <= timedelta(hours=24):
        return "fresh"
    if age <= timedelta(hours=36):
        return "aging"
    return "stale"


def _pick_lifecycle_chip(outcomes: list[dict]) -> dict[str, str]:
    if not outcomes:
        return {"label": "Open", "tone": "neutral"}

    hit_target = any(bool(row.get("hit_target")) for row in outcomes)
    hit_stop = any(bool(row.get("hit_stop")) for row in outcomes)
    if hit_stop:
        return {"label": "Stopped", "tone": "bad"}
    if hit_target:
        return {"label": "Target Hit", "tone": "good"}

    fully_evaluated = {
        int(row.get("horizon_days") or 0)
        for row in outcomes
        if int(row.get("bars_available") or 0) >= int(row.get("horizon_days") or 0) > 0
    }
    if 10 in fully_evaluated:
        return {"label": "10D Evaluated", "tone": "good"}
    if 5 in fully_evaluated:
        return {"label": "5D Evaluated", "tone": "warn"}
    return {"label": "Pending Eval", "tone": "neutral"}


def _empty_price_chart() -> dict[str, Any]:
    return {
        "points": "",
        "change_pct": None,
        "change_display": "-",
        "latest": None,
        "state": "none",
    }


def _build_price_sparklines(tickers: list[str]) -> dict[str, dict[str, Any]]:
    now = datetime.now(timezone.utc)
    unique_tickers = [str(t).strip() for t in dict.fromkeys(tickers) if str(t).strip()]
    charts: dict[str, dict[str, Any]] = {}
    to_fetch: list[str] = []

    for ticker in unique_tickers:
        cached = _PRICE_SPARKLINE_CACHE.get(ticker)
        if cached:
            fetched_at = cached.get("fetched_at")
            if isinstance(fetched_at, datetime) and (now - fetched_at) <= PRICE_SPARKLINE_TTL:
                charts[ticker] = dict(cached.get("chart") or _empty_price_chart())
                continue
        to_fetch.append(ticker)

    if to_fetch:
        try:
            history = download_price_history(
                to_fetch,
                period="3mo",
                chunk_size=20,
                sleep_seconds=0.0,
                retries=1,
                timeout_seconds=15,
            )

            for ticker in to_fetch:
                chart = _empty_price_chart()
                frame = extract_ticker_frame(history, ticker)
                if not frame.empty and "Close" in frame.columns:
                    closes = frame["Close"].dropna().astype(float).tail(30).tolist()
                    if len(closes) >= 2:
                        start = closes[0]
                        latest = closes[-1]
                        change_pct = ((latest / start) - 1.0) * 100.0 if start else None
                        chart = {
                            "points": _build_sparkline_points(closes),
                            "change_pct": change_pct,
                            "change_display": (
                                f"{change_pct:+.2f}%" if change_pct is not None else "-"
                            ),
                            "latest": latest,
                            "state": "up" if (change_pct is not None and change_pct >= 0) else "down",
                        }

                charts[ticker] = chart
                _PRICE_SPARKLINE_CACHE[ticker] = {"fetched_at": now, "chart": chart}

        except Exception:
            # Keep dashboard responsive even if market data API is unavailable.
            for ticker in to_fetch:
                chart = _PRICE_SPARKLINE_CACHE.get(ticker, {}).get("chart") or _empty_price_chart()
                charts[ticker] = dict(chart)

    for ticker in unique_tickers:
        charts.setdefault(ticker, _empty_price_chart())

    return charts


def _build_sparkline_points(
    values: list[float],
    width: int = 320,
    height: int = 90,
    pad: int = 8,
) -> str:
    if not values:
        return ""

    if len(values) == 1:
        x = width // 2
        y = height // 2
        return f"{x},{y}"

    vmin = min(values)
    vmax = max(values)
    span = vmax - vmin
    if span == 0:
        span = 1.0

    usable_w = max(1, width - (2 * pad))
    usable_h = max(1, height - (2 * pad))

    points: list[str] = []
    for i, value in enumerate(values):
        x = pad + (i * usable_w / (len(values) - 1))
        y = pad + ((vmax - value) / span) * usable_h
        points.append(f"{x:.1f},{y:.1f}")

    return " ".join(points)


def _sparkline_scaling(
    values: list[float],
    width: int = 320,
    height: int = 90,
    pad: int = 8,
) -> tuple[float, float, float, float, float]:
    vmin = min(values)
    vmax = max(values)
    span = vmax - vmin
    if span == 0:
        span = 1.0

    usable_w = max(1, width - (2 * pad))
    usable_h = max(1, height - (2 * pad))

    def y_for(value: float) -> float:
        return pad + ((vmax - value) / span) * usable_h

    zero_y = y_for(0.0)
    return vmin, vmax, usable_w, zero_y, pad


def _build_sparkline_segments(
    values: list[float],
    width: int = 320,
    height: int = 90,
    pad: int = 8,
) -> tuple[list[dict[str, str]], float]:
    if not values:
        return [], height / 2

    if len(values) == 1:
        x = width // 2
        y = height // 2
        color = "good" if values[0] >= 0 else "bad"
        return [{"points": f"{x},{y}", "color": color}], float(y)

    vmin, vmax, usable_w, zero_y, pad_val = _sparkline_scaling(values, width=width, height=height, pad=pad)
    span = vmax - vmin
    if span == 0:
        span = 1.0
    usable_h = max(1, height - (2 * pad_val))

    def y_for(value: float) -> float:
        return pad_val + ((vmax - value) / span) * usable_h

    xs = [pad_val + (i * usable_w / (len(values) - 1)) for i in range(len(values))]
    pts = list(zip(xs, values))

    def color_for(value: float) -> str:
        return "good" if value >= 0 else "bad"

    segments: list[dict[str, str]] = []
    current_color = color_for(values[0])
    current_points: list[tuple[float, float]] = [(pts[0][0], y_for(pts[0][1]))]

    for i in range(1, len(pts)):
        x0, v0 = pts[i - 1]
        x1, v1 = pts[i]
        y0 = y_for(v0)
        y1 = y_for(v1)

        crosses_zero = (v0 < 0 < v1) or (v0 > 0 > v1)
        if crosses_zero:
            t = (0.0 - v0) / (v1 - v0)
            zx = x0 + ((x1 - x0) * t)
            zy = y_for(0.0)

            current_points.append((zx, zy))
            segments.append(
                {
                    "color": current_color,
                    "points": " ".join(f"{x:.1f},{y:.1f}" for x, y in current_points),
                }
            )

            current_color = color_for(v1)
            current_points = [(zx, zy), (x1, y1)]
            continue

        next_color = color_for(v1)
        if next_color != current_color and current_points:
            segments.append(
                {
                    "color": current_color,
                    "points": " ".join(f"{x:.1f},{y:.1f}" for x, y in current_points),
                }
            )
            current_color = next_color
            current_points = [(x0, y0), (x1, y1)]
        else:
            current_points.append((x1, y1))

    if current_points:
        segments.append(
            {
                "color": current_color,
                "points": " ".join(f"{x:.1f},{y:.1f}" for x, y in current_points),
            }
        )

    return segments, zero_y


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

    run_dict = dict(latest_run)

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

    outcome_summary_raw = get_outcome_summary_by_horizon(settings.database_path)
    outcome_summary: dict[int, dict] = {}
    for row in outcome_summary_raw:
        horizon = int(row["horizon_days"])
        evaluated = int(row.get("evaluated_count") or 0)
        hit_target_count = int(row.get("hit_target_count") or 0)
        hit_stop_count = int(row.get("hit_stop_count") or 0)

        outcome_summary[horizon] = {
            "horizon_days": horizon,
            "evaluated_count": evaluated,
            "avg_return_pct": row.get("avg_return_pct"),
            "avg_mfe_pct": row.get("avg_mfe_pct"),
            "avg_mae_pct": row.get("avg_mae_pct"),
            "target_hit_pct": ((hit_target_count / evaluated) * 100.0) if evaluated > 0 else None,
            "stop_hit_pct": ((hit_stop_count / evaluated) * 100.0) if evaluated > 0 else None,
        }

    recent_outcomes = get_recent_pick_outcomes(settings.database_path, limit=20)

    picks_list = [dict(row) for row in picks]
    pick_ids = [int(p["id"]) for p in picks_list]

    outcomes_by_pick: dict[int, list[dict]] = {pick_id: [] for pick_id in pick_ids}
    if pick_ids:
        placeholders = ",".join("?" for _ in pick_ids)
        pick_outcomes_rows = conn.execute(
            f"""
            SELECT pick_id, horizon_days, bars_available, hit_target, hit_stop
            FROM pick_outcomes
            WHERE pick_id IN ({placeholders})
            """,
            tuple(pick_ids),
        ).fetchall()

        for row in pick_outcomes_rows:
            row_dict = dict(row)
            outcomes_by_pick.setdefault(int(row_dict["pick_id"]), []).append(row_dict)

    conn.close()

    trend_values: dict[int, list[float]] = {5: [], 10: []}
    for row in reversed(recent_outcomes):
        try:
            horizon = int(row.get("horizon_days") or 0)
        except (TypeError, ValueError):
            continue

        if horizon not in trend_values:
            continue

        bars_available = int(row.get("bars_available") or 0)
        ret = row.get("outcome_return_pct")
        if ret is None or bars_available < horizon:
            continue

        trend_values[horizon].append(float(ret))

    outcome_trends: dict[int, dict] = {}
    for horizon, values in trend_values.items():
        series = values[-20:]
        segments, zero_y = _build_sparkline_segments(series)
        outcome_trends[horizon] = {
            "values": series,
            "points": _build_sparkline_points(series),
            "segments": segments,
            "zero_y": zero_y,
            "min": min(series) if series else None,
            "max": max(series) if series else None,
            "latest": series[-1] if series else None,
        }

    run_at = parse_iso_utc(run_dict["run_at_utc"])
    now_utc = datetime.now(timezone.utc)
    age = now_utc - run_at
    run_dict["is_stale"] = age > timedelta(hours=36)
    run_dict["age_seconds"] = int(age.total_seconds())
    run_dict["age_label"] = _format_age_label(age)

    # Backward-compatible display fields for the dashboard template.
    run_dict["regime_latest"] = run_dict.get("regime_price")
    run_dict["regime_ma"] = run_dict.get("regime_ma_fast")
    run_dict["regime_ma_days"] = settings.market_regime_fast_ma
    run_dict["regime_ma_slow_days"] = settings.market_regime_slow_ma
    run_dict["regime_bullish"] = run_dict.get("regime_state") == "bullish"

    scan_freshness = {
        "state": _freshness_state(age),
        "label": run_dict["age_label"],
        "timestamp": run_dict["run_at_utc"],
    }

    latest_eval = None
    eval_freshness = {"state": "none", "label": "no evaluations yet", "timestamp": None}
    if recent_outcomes:
        latest_eval = max(recent_outcomes, key=lambda row: row.get("evaluated_at_utc") or "")
    if latest_eval and latest_eval.get("evaluated_at_utc"):
        eval_at = parse_iso_utc(str(latest_eval["evaluated_at_utc"]))
        eval_age = now_utc - eval_at
        eval_freshness = {
            "state": _freshness_state(eval_age),
            "label": _format_age_label(eval_age),
            "timestamp": str(latest_eval["evaluated_at_utc"]),
        }

    evaluated_returns = [
        float(row["outcome_return_pct"])
        for row in recent_outcomes
        if row.get("outcome_return_pct") is not None
        and int(row.get("bars_available") or 0) >= int(row.get("horizon_days") or 0)
    ]
    positive_count = len([value for value in evaluated_returns if value > 0])
    recent_count = len(evaluated_returns)
    target_hits = len([row for row in recent_outcomes if bool(row.get("hit_target"))])
    stop_hits = len([row for row in recent_outcomes if bool(row.get("hit_stop"))])

    kpi_strip = {
        "evaluated_count": recent_count,
        "win_rate_pct": ((positive_count / recent_count) * 100.0) if recent_count else None,
        "avg_return_pct": (sum(evaluated_returns) / recent_count) if recent_count else None,
        "target_hits": target_hits,
        "stop_hits": stop_hits,
    }

    for pick in picks_list:
        pick_id = int(pick["id"])
        pick["lifecycle"] = _pick_lifecycle_chip(outcomes_by_pick.get(pick_id, []))

    candidate_list = [dict(row) for row in candidates]
    top_candidate_tickers = [c["ticker"] for c in candidate_list[:5]]
    price_sparklines = _build_price_sparklines(top_candidate_tickers)
    for c in candidate_list[:5]:
        c["price_chart"] = price_sparklines.get(c["ticker"], _empty_price_chart())

    return {
        "run": run_dict,
        "candidates": candidate_list,
        "picks": picks_list,
        "outcome_summary": outcome_summary,
        "recent_outcomes": recent_outcomes,
        "outcome_trends": outcome_trends,
        "freshness": {
            "scan": scan_freshness,
            "evaluation": eval_freshness,
        },
        "kpi_strip": kpi_strip,
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

    max_age = timedelta(hours=36)
    age = now - run_at
    is_healthy = age <= max_age

    payload = {
        "status": "healthy" if is_healthy else "stale",
        "last_scan_utc": latest["run_at_utc"],
        "age_seconds": int(age.total_seconds()),
        "should_trade": bool(latest["should_trade"]),
        "regime_state": latest.get("regime_state"),
        "winner_ticker": latest["winner_ticker"],
    }

    return jsonify(payload), 200 if is_healthy else 503


@app.route("/")
def dashboard():
    data = load_dashboard_data()
    return render_template("dashboard.html", data=data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)