from __future__ import annotations

import requests

from .config import Settings
from .scoring import ScoredCandidate


def build_trade_webhook_payload(candidate, top_candidates, settings):

    currency_symbol = "$" if candidate.market == "US" else "£"

    buy_price = candidate.latest_close
    target_price = buy_price * (1 + settings.target_profit_pct / 100)
    stop_price = buy_price * (1 - settings.stop_loss_pct / 100)

    leaderboard = "\n".join(
        [
            f"{i+1}. {c.ticker}  score {c.score:.2f}"
            for i, c in enumerate(top_candidates[:5])
        ]
    )

    return {
        "username": settings.webhook_username,
        "content": "📈 Momentum scan results",
        "embeds": [
            {
                "title": f"Winner: {candidate.ticker}",
                "description": (
                    f"**Buy:** {currency_symbol}{buy_price:.2f}\n"
                    f"**Target:** {currency_symbol}{target_price:.2f}\n"
                    f"**Stop:** {currency_symbol}{stop_price:.2f}\n\n"
                    f"**Top 5 Candidates:**\n{leaderboard}"
                ),
            }
        ],
    }


def build_no_trade_webhook_payload(reason: str, settings: Settings) -> dict:
    return {
        "username": settings.webhook_username,
        "content": "⏸️ Momentum bot: no trade today.",
        "embeds": [
            {
                "title": "No Trade",
                "description": reason,
            }
        ],
    }


def send_trade_webhook(candidate: ScoredCandidate, settings: Settings, timeout_seconds: int = 15) -> None:
    print("Sending trade webhook notification...")

    if not settings.webhook_url:
        raise RuntimeError("WEBHOOK_URL is not configured")

    payload = build_trade_webhook_payload(candidate, settings)
    response = requests.post(settings.webhook_url, json=payload, timeout=timeout_seconds)
    response.raise_for_status()


def send_no_trade_webhook(reason: str, settings: Settings, timeout_seconds: int = 15) -> None:
    print(f"Sending no-trade webhook notification: {reason}")

    if not settings.webhook_url:
        raise RuntimeError("WEBHOOK_URL is not configured")

    payload = build_no_trade_webhook_payload(reason, settings)
    response = requests.post(settings.webhook_url, json=payload, timeout=timeout_seconds)
    response.raise_for_status()