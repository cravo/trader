# Trader

A small Python app that:

- downloads market data from Yahoo Finance
- scores candidates using:
  - 5-day return
  - relative strength vs market benchmark
  - volume ratio vs prior 30-day average
  - breakout above recent highs
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

## Extra improvement in this version

This version adds a simple trend filter:

- latest close must be above slow MA
- fast MA must be above slow MA

By default:

- fast MA = 20 days
- slow MA = 50 days

## Setup

```bash
cp .env.example .env