from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta

from flask import Flask, render_template, jsonify

from .config import Settings


app = Flask(__name__)
settings = Settings()


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def parse_iso_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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

    conn.close()

    run_at = parse_iso_utc(run_dict["run_at_utc"])
    age = datetime.now(timezone.utc) - run_at
    run_dict["is_stale"] = age > timedelta(hours=36)
    run_dict["age_seconds"] = int(age.total_seconds())

    return {
        "run": run_dict,
        "candidates": [dict(row) for row in candidates],
        "picks": [dict(row) for row in picks],
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