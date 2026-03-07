from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .scoring import ScoredCandidate


SCAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at_utc TEXT NOT NULL,
    universe_size INTEGER NOT NULL,
    regime_ticker TEXT NOT NULL,
    regime_ma_days INTEGER NOT NULL,
    regime_latest REAL,
    regime_ma REAL,
    regime_bullish INTEGER NOT NULL,
    should_trade INTEGER NOT NULL,
    decision_reason TEXT NOT NULL,
    winner_ticker TEXT,
    winner_name TEXT,
    winner_market TEXT,
    winner_score REAL
);
"""


SCAN_CANDIDATES_SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_run_id INTEGER NOT NULL,
    rank INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL,
    market TEXT NOT NULL,
    index_name TEXT NOT NULL,
    latest_close REAL NOT NULL,
    weekly_change_pct REAL NOT NULL,
    monthly_change_pct REAL,
    relative_strength_pct REAL NOT NULL,
    volume_ratio REAL NOT NULL,
    breakout_flag INTEGER NOT NULL,
    trend_ok INTEGER NOT NULL,
    score REAL NOT NULL,
    FOREIGN KEY(scan_run_id) REFERENCES scan_runs(id)
);
"""


PICKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    picked_at_utc TEXT NOT NULL,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL,
    market TEXT NOT NULL,
    latest_close REAL NOT NULL,
    target_price REAL NOT NULL,
    stop_price REAL NOT NULL,
    score REAL NOT NULL
);
"""


def get_connection(database_path: str) -> sqlite3.Connection:

    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)

    conn.execute(SCAN_SCHEMA)
    conn.execute(SCAN_CANDIDATES_SCHEMA)
    conn.execute(PICKS_SCHEMA)

    conn.commit()

    return conn


def save_scan_run(
    database_path: str,
    universe_size: int,
    regime_ticker: str,
    regime_ma_days: int,
    regime_latest: float | None,
    regime_ma: float | None,
    regime_bullish: bool,
    should_trade: bool,
    decision_reason: str,
    winner: ScoredCandidate | None,
) -> int:

    conn = get_connection(database_path)

    run_time = datetime.now(timezone.utc).isoformat()

    cursor = conn.execute(
        """
        INSERT INTO scan_runs (
            run_at_utc,
            universe_size,
            regime_ticker,
            regime_ma_days,
            regime_latest,
            regime_ma,
            regime_bullish,
            should_trade,
            decision_reason,
            winner_ticker,
            winner_name,
            winner_market,
            winner_score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_time,
            universe_size,
            regime_ticker,
            regime_ma_days,
            regime_latest,
            regime_ma,
            1 if regime_bullish else 0,
            1 if should_trade else 0,
            decision_reason,
            winner.ticker if winner else None,
            winner.name if winner else None,
            winner.market if winner else None,
            winner.score if winner else None,
        ),
    )

    conn.commit()

    scan_id = cursor.lastrowid

    conn.close()

    return scan_id


def save_scan_candidates(
    database_path: str,
    scan_id: int,
    candidates: list[ScoredCandidate],
    limit: int = 10,
) -> None:

    conn = get_connection(database_path)

    for rank, c in enumerate(candidates[:limit], start=1):

        conn.execute(
            """
            INSERT INTO scan_candidates (
                scan_run_id,
                rank,
                ticker,
                name,
                market,
                index_name,
                latest_close,
                weekly_change_pct,
                monthly_change_pct,
                relative_strength_pct,
                volume_ratio,
                breakout_flag,
                trend_ok,
                score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scan_id,
                rank,
                c.ticker,
                c.name,
                c.market,
                c.index_name,
                c.latest_close,
                c.weekly_change_pct,
                getattr(c, "monthly_change_pct", None),
                c.relative_strength_pct,
                c.volume_ratio,
                c.breakout_flag,
                1 if c.trend_ok else 0,
                c.score,
            ),
        )

    conn.commit()
    conn.close()


def save_pick(database_path: str, winner: ScoredCandidate, target: float, stop: float):

    conn = get_connection(database_path)

    conn.execute(
        """
        INSERT INTO picks (
            picked_at_utc,
            ticker,
            name,
            market,
            latest_close,
            target_price,
            stop_price,
            score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            winner.ticker,
            winner.name,
            winner.market,
            winner.latest_close,
            target,
            stop,
            winner.score,
        ),
    )

    conn.commit()
    conn.close()