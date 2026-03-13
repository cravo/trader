from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .scoring import ScoredCandidate


SCAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at_utc TEXT NOT NULL,
    universe_size INTEGER NOT NULL,
    regime_ticker TEXT NOT NULL,
    regime_state TEXT NOT NULL,
    regime_price REAL,
    regime_ma_fast REAL,
    regime_ma_slow REAL,
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


PICK_OUTCOMES_SCHEMA = """
CREATE TABLE IF NOT EXISTS pick_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pick_id INTEGER NOT NULL,
    horizon_days INTEGER NOT NULL,
    evaluated_at_utc TEXT NOT NULL,
    bars_available INTEGER NOT NULL,
    outcome_close REAL,
    outcome_return_pct REAL,
    max_favorable_pct REAL,
    max_adverse_pct REAL,
    hit_target INTEGER NOT NULL,
    hit_stop INTEGER NOT NULL,
    notes TEXT,
    UNIQUE(pick_id, horizon_days),
    FOREIGN KEY(pick_id) REFERENCES picks(id)
);
"""


def get_connection(database_path: str) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)

    conn.execute(SCAN_SCHEMA)
    conn.execute(SCAN_CANDIDATES_SCHEMA)
    conn.execute(PICKS_SCHEMA)
    conn.execute(PICK_OUTCOMES_SCHEMA)

    conn.commit()
    return conn


def save_scan_run(
    database_path: str,
    universe_size: int,
    regime_ticker: str,
    regime_state: str,
    regime_price: float | None,
    regime_ma_fast: float | None,
    regime_ma_slow: float | None,
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
            regime_state,
            regime_price,
            regime_ma_fast,
            regime_ma_slow,
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
            regime_state,
            regime_price,
            regime_ma_fast,
            regime_ma_slow,
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


def save_pick(database_path: str, winner: ScoredCandidate, target: float, stop: float) -> None:
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


def list_picks(database_path: str, limit: int | None = None) -> list[dict[str, Any]]:
    conn = get_connection(database_path)
    conn.row_factory = sqlite3.Row

    if limit is not None and limit > 0:
        rows = conn.execute(
            """
            SELECT *
            FROM picks
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT *
            FROM picks
            ORDER BY id DESC
            """
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def save_pick_outcome(
    database_path: str,
    pick_id: int,
    horizon_days: int,
    bars_available: int,
    outcome_close: float | None,
    outcome_return_pct: float | None,
    max_favorable_pct: float | None,
    max_adverse_pct: float | None,
    hit_target: bool,
    hit_stop: bool,
    notes: str | None = None,
) -> None:
    conn = get_connection(database_path)

    conn.execute(
        """
        INSERT INTO pick_outcomes (
            pick_id,
            horizon_days,
            evaluated_at_utc,
            bars_available,
            outcome_close,
            outcome_return_pct,
            max_favorable_pct,
            max_adverse_pct,
            hit_target,
            hit_stop,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(pick_id, horizon_days)
        DO UPDATE SET
            evaluated_at_utc=excluded.evaluated_at_utc,
            bars_available=excluded.bars_available,
            outcome_close=excluded.outcome_close,
            outcome_return_pct=excluded.outcome_return_pct,
            max_favorable_pct=excluded.max_favorable_pct,
            max_adverse_pct=excluded.max_adverse_pct,
            hit_target=excluded.hit_target,
            hit_stop=excluded.hit_stop,
            notes=excluded.notes
        """,
        (
            pick_id,
            horizon_days,
            datetime.now(timezone.utc).isoformat(),
            bars_available,
            outcome_close,
            outcome_return_pct,
            max_favorable_pct,
            max_adverse_pct,
            1 if hit_target else 0,
            1 if hit_stop else 0,
            notes,
        ),
    )

    conn.commit()
    conn.close()


def get_outcome_summary_by_horizon(database_path: str) -> list[dict[str, Any]]:
    conn = get_connection(database_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT
            horizon_days,
            COUNT(*) AS evaluated_count,
            AVG(outcome_return_pct) AS avg_return_pct,
            AVG(max_favorable_pct) AS avg_mfe_pct,
            AVG(max_adverse_pct) AS avg_mae_pct,
            SUM(hit_target) AS hit_target_count,
            SUM(hit_stop) AS hit_stop_count
        FROM pick_outcomes
        WHERE bars_available >= horizon_days
        GROUP BY horizon_days
        ORDER BY horizon_days ASC
        """
    ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def get_recent_pick_outcomes(database_path: str, limit: int = 20) -> list[dict[str, Any]]:
    conn = get_connection(database_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT
            po.evaluated_at_utc,
            po.horizon_days,
            po.bars_available,
            po.outcome_return_pct,
            po.max_favorable_pct,
            po.max_adverse_pct,
            po.hit_target,
            po.hit_stop,
            po.notes,
            p.picked_at_utc,
            p.ticker,
            p.market,
            p.latest_close,
            p.target_price,
            p.stop_price
        FROM pick_outcomes po
        JOIN picks p ON p.id = po.pick_id
        ORDER BY po.evaluated_at_utc DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    conn.close()
    return [dict(r) for r in rows]
