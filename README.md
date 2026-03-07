# Trader

A small Python app to recommend swing trades, based on a one-week time horizon and 5% gain:

- downloads market data from Yahoo Finance
- scores candidates using various metrics
- applies market regime and trend filters
- either:
  - selects one stock for the day/week
  - or decides there is no trade
- stores picks in SQLite
- optionally sends Discord/webhook notifications

## Supported universes

- FTSE 100
- FTSE 250
- S&P 500
- Nasdaq-100

## Relative strength

- UK stocks are compared against `^FTSE`
- US stocks are compared against `^GSPC`

## Setup

```bash
cp .env.example .env
docker compose build
docker compose up -d trader-web
docker compose run --rm trader-scan

crontab -e
10 8 * * 1-5 cd ~/trader && docker compose run --rm trader-scan >> /var/log/trader-scan.log 2>&1

