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
```

## Evaluate Pick Outcomes

Run from Docker (uses the same mounted `/data/momentum.db` database):

```bash
docker compose run --rm trader-scan python -m trader.cli evaluate --horizons 5,10 --limit 200
```

Run locally (non-Docker):

```bash
PYTHONPATH=src DATABASE_PATH=data/momentum.db python -m trader.cli evaluate --horizons 5,10 --limit 200
```

## Backtest

Run a historical replay of the current selection logic:

```bash
PYTHONPATH=src DATABASE_PATH=data/momentum.db python -m trader.cli backtest --lookback-period 3y --horizon-days 5 --max-days 180 --step-days 5
```

Notes:
- `--step-days 5` approximates weekly signal evaluation and runs much faster than daily.
- `--horizon-days` should typically match your intended hold period.

## Cron Examples

```bash
crontab -e

# Weekday scan job (08:10)
10 8 * * 1-5 cd ~/trader && docker compose run --rm trader-scan >> /var/log/trader-scan.log 2>&1

# Weekly universe refresh (Monday 06:00)
0 6 * * 1 cd ~/trader && python3 scripts/update_universe.py >> /var/log/trader-universe.log 2>&1

# Nightly outcome evaluation (01:15)
15 1 * * * cd ~/trader && docker compose run --rm trader-scan python -m trader.cli evaluate --horizons 5,10 --limit 200 >> /var/log/trader-evaluate.log 2>&1
```

