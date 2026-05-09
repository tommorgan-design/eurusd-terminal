# Universal Bracket Engine v1.0

## What It Does

Takes any currency pair and produces a complete bracket trading parameter card — the optimal range filter, entry offset, take profit, trading days, and risk metrics. One build, any pair, five minutes instead of five hours.

## How To Read The Output

The parameter card has these sections:

### Asian Range Profile
Statistics on how wide the Asian session range typically is for this pair. The range = the high minus the low during the 8 hours before London opens.

### Range Band Analysis
Bracket performance grouped by Asian range size. Shows win rate, average pips, and total pips for each 5-pip band. The "sweet spot" is the range band (or span of adjacent bands) that produces the most total pips with a reasonable win rate.

### Day of Week Analysis
Which days have the weakest directional bias — these are the best bracket days. Strong directional days (>55% direction match) are better for directional trades. Weak days (<55%) are where brackets shine because the market is indecisive.

### Entry Offset Optimisation
Tests every combination of entry offset (+3 to +15 pips) and take profit (25 to 50 pips). Shows the best combos for weak-direction days specifically, plus all-days for comparison.

### Side Analysis
Whether buy brackets or sell brackets perform differently. A balanced pair (similar win rates) is ideal.

### Time to Trigger
How long after London open the bracket typically fires. Tells you when to expect action.

### Compression Ratio
Asian range divided by previous day's range. COMPRESSED (<50%) means the market is coiling — good for breakout.

### Recommended Parameters
The final parameter card — range filter, offset, TP, days, estimated annual pips, and risk metrics.

## How To Run It

```
python universal_bracket_engine.py EURUSD
python universal_bracket_engine.py GBPUSD
python universal_bracket_engine.py EURUSD GBPUSD AUDUSD
```

Requires: Python 3.10+, yfinance, pandas, numpy.

Or with uv: `uv run --with yfinance,pandas,numpy python3 universal_bracket_engine.py GBPUSD`

## Available Pairs

EUR/USD, GBP/USD, USD/JPY, AUD/USD, NZD/USD, USD/CAD, USD/CHF, USD/NOK

## Key Concepts

- **Asian Session**: 8 hours before London open (auto-adjusts for BST/GMT)
- **Bracket Trade**: Two pending orders placed at Asian high + offset (buy) and Asian low - offset (sell). When one fires, the other is the stop.
- **Whipsaw**: Both levels hit in the same bar — ambiguous, counted separately.
- **Risk**: Range size + (2 × offset). The wider the range, the more risk per trade.

## Monthly Review

Run the engine monthly to check parameters are still optimal. Market character changes with regimes — parameters that worked in low volatility may need adjustment in high volatility.

## Data Source

yfinance hourly bars (UTC). Approximately 2.8 years of data (as of May 2026). Asian range calculated from bar highs/lows — adequate for strategic parameter discovery but slightly less precise than tick-level data.

---
*Built by Chief for Tom Morgan's bracket trading system.*
*Chief collects · Claude analyses · Tom decides.*
