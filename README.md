# Trader

[![Tests](https://img.shields.io/github/actions/workflow/status/cravo/trader/tests.yml?branch=main&label=tests)](https://github.com/cravo/trader/actions/workflows/tests.yml)

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

- S&P 500
- Nasdaq-100

## Relative strength

- US stocks are compared against `^GSPC`

## Setup

```bash
cp .env.example .env
python3 venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/update_universe.py >> /var/log/trader-universe.log 2>&1
docker compose build
docker compose up -d trader-web
docker compose run --rm trader-scan

crontab -e
10 8 * * 1-5 cd ~/trader && docker compose run --rm trader-scan >> /var/log/trader-scan.log 2>&1
0 6 * * 1 cd ~/trader && python3 scripts/update_universe.py >> /var/log/trader-universe.log 2>&1

