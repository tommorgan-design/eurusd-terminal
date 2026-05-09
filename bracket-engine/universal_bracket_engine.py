#!/usr/bin/env python3
"""
Universal Bracket Engine v1.0
Built by Chief for Tom Morgan's bracket trading system.

Takes any currency pair, outputs a complete bracket parameter card.
One build, any pair, five minutes not five hours.

Usage:
    python universal_bracket_engine.py EURUSD
    python universal_bracket_engine.py GBPUSD
    python universal_bracket_engine.py EURUSD GBPUSD   (multiple pairs)
"""

import sys
import json
import warnings
warnings.filterwarnings('ignore')

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo

# ============================================================
# PAIR CONFIGURATION
# ============================================================

PAIR_CONFIG = {
    'EURUSD': {'ticker': 'EURUSD=X', 'pip': 0.0001, 'name': 'EUR/USD'},
    'GBPUSD': {'ticker': 'GBPUSD=X', 'pip': 0.0001, 'name': 'GBP/USD'},
    'USDJPY': {'ticker': 'USDJPY=X', 'pip': 0.01,   'name': 'USD/JPY'},
    'AUDUSD': {'ticker': 'AUDUSD=X', 'pip': 0.0001, 'name': 'AUD/USD'},
    'NZDUSD': {'ticker': 'NZDUSD=X', 'pip': 0.0001, 'name': 'NZD/USD'},
    'USDCAD': {'ticker': 'USDCAD=X', 'pip': 0.0001, 'name': 'USD/CAD'},
    'USDNOK': {'ticker': 'USDNOK=X', 'pip': 0.0001, 'name': 'USD/NOK'},
    'USDCHF': {'ticker': 'USDCHF=X', 'pip': 0.0001, 'name': 'USD/CHF'},
}

# ============================================================
# TIMEZONE / SESSION HELPERS
# ============================================================

LONDON_TZ = ZoneInfo('Europe/London')

def is_bst(dt):
    """Check if date falls in British Summer Time."""
    if isinstance(dt, datetime):
        d = dt.date() if hasattr(dt, 'date') else dt
    else:
        d = dt
    london_dt = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=LONDON_TZ)
    return london_dt.utcoffset() == timedelta(hours=1)

def london_open_utc(d):
    """London open in UTC: 07:00 during BST, 08:00 during GMT."""
    hour = 7 if is_bst(d) else 8
    return datetime(d.year, d.month, d.day, hour, 0, tzinfo=timezone.utc)

def asian_window(d):
    """Asian session = London open minus 8 hours → London open."""
    lo = london_open_utc(d)
    return lo - timedelta(hours=8), lo

def bracket_window_end(d):
    """Bracket expires at NY close = 21:00 UTC."""
    return datetime(d.year, d.month, d.day, 21, 0, tzinfo=timezone.utc)

# ============================================================
# DATA FETCHING
# ============================================================

def fetch_hourly(ticker):
    """Fetch max hourly data from yfinance."""
    print(f"  Fetching hourly data for {ticker}...")

    # Single call with period='730d' — yfinance often returns more than 730 days
    df = yf.download(ticker, period='730d', interval='1h', progress=False)

    if df is None or len(df) == 0:
        raise ValueError(f"No data for {ticker}")

    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    df = df[~df.index.duplicated(keep='first')].sort_index()

    # Ensure UTC
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC')
    elif str(df.index.tz) != 'UTC':
        df.index = df.index.tz_convert('UTC')

    # Remove weekend-only artifacts (Sat/Sun with no real trading)
    df = df[df.index.dayofweek < 5]  # Keep Mon-Fri bars only

    print(f"  {len(df)} bars | {df.index[0].date()} → {df.index[-1].date()}")
    return df

# ============================================================
# SESSION BUILDER
# ============================================================

def build_sessions(hourly, pip):
    """Build per-day session records with Asian range and bracket window data."""
    sessions = []
    dates_seen = sorted(set(hourly.index.date))
    weekdays = [d for d in dates_seen if d.weekday() < 5]

    for d in weekdays:
        try:
            a_start, a_end = asian_window(d)
            b_end = bracket_window_end(d)

            # Asian bars
            a_bars = hourly[(hourly.index >= a_start) & (hourly.index < a_end)]
            if len(a_bars) < 3:
                continue

            a_high = float(a_bars['High'].max())
            a_low  = float(a_bars['Low'].min())
            a_range = round((a_high - a_low) / pip, 1)

            if a_range < 1:  # Filter degenerate ranges
                continue

            # Bracket window bars (London open → NY close)
            b_bars = hourly[(hourly.index >= a_end) & (hourly.index <= b_end)]
            if len(b_bars) < 3:
                continue

            # Body coherence of Asian session
            a_opens  = a_bars['Open'].values
            a_closes = a_bars['Close'].values
            bull_bars = sum(1 for o, c in zip(a_opens, a_closes) if c > o)
            bear_bars = sum(1 for o, c in zip(a_opens, a_closes) if c < o)
            total_bars = len(a_bars)
            body_coherence = max(bull_bars, bear_bars) / total_bars * 100 if total_bars > 0 else 50

            # London session stats
            l_high = float(b_bars['High'].max())
            l_low  = float(b_bars['Low'].min())
            l_close = float(b_bars.iloc[-1]['Close'])

            # Direction: did London break higher or lower relative to Asian midpoint?
            a_mid = (a_high + a_low) / 2
            direction = 'bull' if l_close > a_mid else 'bear'

            # Store bar-level data for bracket simulation
            bar_data = []
            for idx, row in b_bars.iterrows():
                bar_data.append({
                    'high': float(row['High']),
                    'low': float(row['Low']),
                    'open': float(row['Open']),
                    'close': float(row['Close']),
                })

            sessions.append({
                'date': d,
                'day': ['Mon','Tue','Wed','Thu','Fri'][d.weekday()],
                'day_num': d.weekday(),
                'a_high': a_high,
                'a_low': a_low,
                'a_range': a_range,
                'a_coherence': round(body_coherence, 1),
                'l_high': l_high,
                'l_low': l_low,
                'l_close': l_close,
                'direction': direction,
                'bars': bar_data,
            })
        except Exception:
            continue

    return sessions

# ============================================================
# BRACKET SIMULATOR
# ============================================================

def sim_bracket(session, offset, tp, pip):
    """Simulate a single bracket trade. Returns dict with outcome."""
    a_high = session['a_high']
    a_low  = session['a_low']
    bars   = session['bars']

    buy_entry  = a_high + offset * pip
    sell_entry = a_low  - offset * pip
    buy_tp     = buy_entry + tp * pip
    sell_tp    = sell_entry - tp * pip
    buy_stop   = sell_entry          # Opposite bracket level
    sell_stop  = buy_entry

    triggered = None  # 'buy' or 'sell'

    for bar in bars:
        h, l = bar['high'], bar['low']

        if triggered is None:
            buy_hit  = h >= buy_entry
            sell_hit = l <= sell_entry

            if buy_hit and sell_hit:
                return {'side': 'whipsaw', 'pips': 0, 'out': 'whipsaw'}

            if buy_hit:
                triggered = 'buy'
                if h >= buy_tp:
                    return {'side': 'buy', 'pips': tp, 'out': 'win'}
                if l <= buy_stop:
                    return {'side': 'buy', 'pips': -round((buy_entry - buy_stop)/pip, 1), 'out': 'loss'}
                continue

            if sell_hit:
                triggered = 'sell'
                if l <= sell_tp:
                    return {'side': 'sell', 'pips': tp, 'out': 'win'}
                if h >= sell_stop:
                    return {'side': 'sell', 'pips': -round((sell_stop - sell_entry)/pip, 1), 'out': 'loss'}
                continue

        elif triggered == 'buy':
            if h >= buy_tp:
                return {'side': 'buy', 'pips': tp, 'out': 'win'}
            if l <= buy_stop:
                return {'side': 'buy', 'pips': -round((buy_entry - buy_stop)/pip, 1), 'out': 'loss'}

        elif triggered == 'sell':
            if l <= sell_tp:
                return {'side': 'sell', 'pips': tp, 'out': 'win'}
            if h >= sell_stop:
                return {'side': 'sell', 'pips': -round((sell_stop - sell_entry)/pip, 1), 'out': 'loss'}

    # Session expired
    if triggered == 'buy':
        last_close = bars[-1]['close']
        return {'side': 'buy', 'pips': round((last_close - buy_entry)/pip, 1), 'out': 'expired'}
    elif triggered == 'sell':
        last_close = bars[-1]['close']
        return {'side': 'sell', 'pips': round((sell_entry - last_close)/pip, 1), 'out': 'expired'}
    else:
        return {'side': 'none', 'pips': 0, 'out': 'no_trigger'}

# ============================================================
# ANALYSIS MODULES
# ============================================================

def range_profile(sessions):
    """Asian range distribution statistics."""
    r = [s['a_range'] for s in sessions]
    return {
        'n': len(r), 'mean': round(np.mean(r),1), 'median': round(np.median(r),1),
        'std': round(np.std(r),1), 'min': round(min(r),1), 'max': round(max(r),1),
        'p10': round(np.percentile(r,10),1), 'p25': round(np.percentile(r,25),1),
        'p75': round(np.percentile(r,75),1), 'p90': round(np.percentile(r,90),1),
    }

def range_band_analysis(sessions, pip, offset=5, tp=35):
    """Bracket performance by Asian range band."""
    bands = [(10,15),(15,20),(20,25),(25,30),(30,35),(35,40),(40,50),(50,60),(60,80),(80,120)]
    results = []
    for lo, hi in bands:
        ss = [s for s in sessions if lo <= s['a_range'] < hi]
        if len(ss) < 3:
            results.append({'band': f"{lo}-{hi}", 'n': len(ss), 'skip': True})
            continue
        trades = [sim_bracket(s, offset, tp, pip) for s in ss]
        triggered = [t for t in trades if t['side'] not in ('none','whipsaw')]
        whipsaws  = [t for t in trades if t['side'] == 'whipsaw']
        no_trig   = [t for t in trades if t['side'] == 'none']
        wins = [t for t in triggered if t['out'] == 'win']
        all_pips = [t['pips'] for t in triggered]
        total_active = len(triggered) + len(whipsaws)
        results.append({
            'band': f"{lo}-{hi}", 'n': len(ss),
            'trig': len(triggered), 'wins': len(wins),
            'losses': len(triggered) - len(wins),
            'whip': len(whipsaws), 'no_trig': len(no_trig),
            'wr': round(len(wins)/len(triggered)*100,1) if triggered else 0,
            'whip_r': round(len(whipsaws)/total_active*100,1) if total_active else 0,
            'avg': round(np.mean(all_pips),1) if all_pips else 0,
            'total': round(sum(all_pips),1) if all_pips else 0,
            'skip': False,
        })
    return results

def day_analysis(sessions, pip, offset=5, tp=35, rng_lo=25, rng_hi=40):
    """Bracket performance + direction bias by day of week."""
    days = ['Mon','Tue','Wed','Thu','Fri']
    results = []
    for day in days:
        ss = [s for s in sessions if s['day'] == day and rng_lo <= s['a_range'] <= rng_hi]
        if len(ss) < 3:
            results.append({'day': day, 'n': len(ss), 'skip': True})
            continue
        trades = [sim_bracket(s, offset, tp, pip) for s in ss]
        triggered = [t for t in trades if t['side'] not in ('none','whipsaw')]
        whipsaws  = [t for t in trades if t['side'] == 'whipsaw']
        wins = [t for t in triggered if t['out'] == 'win']
        all_pips = [t['pips'] for t in triggered]
        total_active = len(triggered) + len(whipsaws)

        # Direction analysis
        bulls = sum(1 for s in ss if s['direction'] == 'bull')
        bears = len(ss) - bulls
        dir_pct = round(max(bulls, bears)/len(ss)*100, 1)
        bias = 'Bull' if bulls >= bears else 'Bear'

        results.append({
            'day': day, 'n': len(ss),
            'trig': len(triggered), 'wins': len(wins),
            'wr': round(len(wins)/len(triggered)*100,1) if triggered else 0,
            'whip_r': round(len(whipsaws)/total_active*100,1) if total_active else 0,
            'avg': round(np.mean(all_pips),1) if all_pips else 0,
            'total': round(sum(all_pips),1) if all_pips else 0,
            'dir_pct': dir_pct, 'bias': bias, 'bulls': bulls, 'bears': bears,
            'skip': False,
        })
    return results

def offset_optimisation(sessions, pip, rng_lo=25, rng_hi=40, day_filter=None):
    """Grid search: entry offset × TP combinations."""
    offsets = [3, 5, 7, 10, 15]
    tps = [25, 30, 35, 40, 45, 50]
    ss = [s for s in sessions if rng_lo <= s['a_range'] <= rng_hi]
    if day_filter:
        ss = [s for s in ss if s['day'] in day_filter]
    if len(ss) < 5:
        return []

    results = []
    for off in offsets:
        for tp in tps:
            trades = [sim_bracket(s, off, tp, pip) for s in ss]
            triggered = [t for t in trades if t['side'] not in ('none','whipsaw')]
            whipsaws  = [t for t in trades if t['side'] == 'whipsaw']
            if not triggered:
                continue
            wins = [t for t in triggered if t['out'] == 'win']
            all_pips = [t['pips'] for t in triggered]
            total_active = len(triggered) + len(whipsaws)
            results.append({
                'off': off, 'tp': tp, 'sess': len(ss),
                'trig': len(triggered), 'wins': len(wins),
                'wr': round(len(wins)/len(triggered)*100,1),
                'whip_r': round(len(whipsaws)/total_active*100,1) if total_active else 0,
                'avg': round(np.mean(all_pips),1),
                'total': round(sum(all_pips),1),
            })
    return results

def compression_analysis(sessions, pip):
    """Compression ratio: Asian range / previous session range."""
    ratios = []
    for i in range(1, len(sessions)):
        prev_range = (sessions[i-1]['l_high'] - sessions[i-1]['l_low']) / pip
        if prev_range > 5:
            ratio = sessions[i]['a_range'] / prev_range * 100
            ratios.append(ratio)
    if not ratios:
        return {'error': 'Insufficient data'}
    return {
        'mean': round(np.mean(ratios),1), 'median': round(np.median(ratios),1),
        'std': round(np.std(ratios),1),
        'p25': round(np.percentile(ratios,25),1), 'p75': round(np.percentile(ratios,75),1),
        'char': 'COMPRESSED' if np.median(ratios) < 50 else
                'MODERATE' if np.median(ratios) < 100 else 'EXPANDED',
    }

def side_analysis(sessions, pip, offset=5, tp=35, rng_lo=25, rng_hi=40):
    """Win rate split by buy vs sell side."""
    ss = [s for s in sessions if rng_lo <= s['a_range'] <= rng_hi]
    trades = [sim_bracket(s, offset, tp, pip) for s in ss]
    buy_trades  = [t for t in trades if t['side'] == 'buy']
    sell_trades = [t for t in trades if t['side'] == 'sell']
    
    def calc(tlist):
        if not tlist:
            return {'n': 0}
        wins = [t for t in tlist if t['out'] == 'win']
        return {
            'n': len(tlist),
            'wr': round(len(wins)/len(tlist)*100, 1),
            'avg': round(np.mean([t['pips'] for t in tlist]), 1),
            'total': round(sum(t['pips'] for t in tlist), 1),
        }
    return {'buy': calc(buy_trades), 'sell': calc(sell_trades)}

def time_to_trigger(sessions, pip, offset=5, rng_lo=25, rng_hi=40):
    """How many bars after London open until bracket fires (median)."""
    ss = [s for s in sessions if rng_lo <= s['a_range'] <= rng_hi]
    bar_counts = []
    for s in ss:
        a_high, a_low = s['a_high'], s['a_low']
        buy_entry  = a_high + offset * pip
        sell_entry = a_low  - offset * pip
        for i, bar in enumerate(s['bars']):
            if bar['high'] >= buy_entry or bar['low'] <= sell_entry:
                bar_counts.append(i + 1)
                break
    if not bar_counts:
        return None
    return {
        'median_bars': round(np.median(bar_counts), 1),
        'mean_bars': round(np.mean(bar_counts), 1),
        'p25_bars': round(np.percentile(bar_counts, 25), 1),
        'p75_bars': round(np.percentile(bar_counts, 75), 1),
        'median_hours': round(np.median(bar_counts), 1),  # 1 bar = 1 hour
    }

# ============================================================
# FIND SWEET SPOT + WEAK DAYS + BEST PARAMS
# ============================================================

def find_sweet_spot(rba):
    """Best range band by total pips (min 8 sessions)."""
    valid = [r for r in rba if not r.get('skip') and r['n'] >= 8 and r['total'] > 0]
    if not valid:
        valid = [r for r in rba if not r.get('skip') and r['n'] >= 5 and r['total'] > 0]
    if not valid:
        return None
    return max(valid, key=lambda x: x['total'])

def find_adjacent_sweet(rba):
    """Find best contiguous range band span (2-3 adjacent bands)."""
    valid = [r for r in rba if not r.get('skip')]
    if len(valid) < 2:
        return None
    
    best_span = None
    best_total = -999999
    for width in [2, 3]:
        for i in range(len(valid) - width + 1):
            span = valid[i:i+width]
            total = sum(r['total'] for r in span)
            sessions = sum(r['n'] for r in span)
            if sessions >= 15 and total > best_total:
                best_total = total
                lo_band = span[0]['band'].split('-')[0]
                hi_band = span[-1]['band'].split('-')[1]
                avg_wr = np.mean([r['wr'] for r in span if r['trig'] > 0])
                best_span = {
                    'band': f"{lo_band}-{hi_band}",
                    'n': sessions,
                    'total': round(best_total, 1),
                    'wr': round(avg_wr, 1),
                }
    return best_span

def find_weak_days(da):
    """Days with direction match < 55% = best bracket candidates."""
    valid = [d for d in da if not d.get('skip')]
    weak = [d['day'] for d in sorted(valid, key=lambda x: x['dir_pct']) if d['dir_pct'] < 55]
    if not weak:
        weak = [d['day'] for d in sorted(valid, key=lambda x: x['dir_pct'])[:2]]
    return weak

def find_best_params(opts):
    """Best offset/TP combo by weighted score."""
    if not opts:
        return None
    for r in opts:
        rate_factor = max(0, (r['wr'] - 40) / 60)
        r['score'] = r['total'] * (0.5 + 0.5 * rate_factor)
    return max(opts, key=lambda x: x['score'])

# ============================================================
# PARAMETER CARD FORMATTER
# ============================================================

def format_card(pair_name, sessions, rp, rba, da, opts_weak, opts_all,
                comp, sides, ttf, sweet, adj_sweet, weak_days, best_p):
    """Format the complete parameter card as text."""
    L = []
    w = 65

    L.append("=" * w)
    L.append(f"  UNIVERSAL BRACKET ENGINE — {pair_name}")
    L.append("=" * w)
    L.append(f"  Generated : {datetime.now().strftime('%Y-%m-%d %H:%M')} NZT")
    L.append(f"  Sessions  : {len(sessions)}")
    if sessions:
        L.append(f"  Period    : {sessions[0]['date']} → {sessions[-1]['date']}")
        years = max((sessions[-1]['date'] - sessions[0]['date']).days / 365, 0.5)
        L.append(f"  Span      : {years:.1f} years")
    L.append("=" * w)

    # --- Asian Range Profile ---
    L.append("\n─── ASIAN RANGE PROFILE ───\n")
    L.append(f"  Mean:    {rp['mean']} pips    Median: {rp['median']} pips")
    L.append(f"  Std Dev: {rp['std']} pips     Min: {rp['min']}  Max: {rp['max']}")
    L.append(f"  10th: {rp['p10']}  25th: {rp['p25']}  75th: {rp['p75']}  90th: {rp['p90']}")

    # --- Range Band Analysis ---
    L.append("\n─── RANGE BAND ANALYSIS (offset +5/-5, TP 35) ───\n")
    L.append(f"  {'Band':<8} {'Sess':>5} {'Trig':>5} {'Win':>4} {'Win%':>6} {'Whip%':>6} {'Avg':>7} {'Total':>8}")
    L.append("  " + "─" * 55)
    for r in rba:
        if r.get('skip'):
            L.append(f"  {r['band']:<8} {r['n']:>5}   — insufficient data")
        else:
            flag = " 🔥" if r['total'] > 100 else " ✅" if r['total'] > 0 else " ❌"
            L.append(f"  {r['band']:<8} {r['n']:>5} {r['trig']:>5} {r['wins']:>4} "
                     f"{r['wr']:>5.1f}% {r['whip_r']:>5.1f}% {r['avg']:>+6.1f} {r['total']:>+7.1f}{flag}")

    if sweet:
        L.append(f"\n  ★ SINGLE BEST BAND: {sweet['band']} ({sweet['wr']:.1f}% win, {sweet['total']:+.1f} pips)")
    if adj_sweet:
        L.append(f"  ★ BEST SPAN:        {adj_sweet['band']} ({adj_sweet['wr']:.1f}% win, {adj_sweet['total']:+.1f} pips)")

    # --- Day of Week ---
    rng_label = f"{sweet['band']}" if sweet else "default"
    L.append(f"\n─── DAY OF WEEK (range {rng_label}, offset +5/-5, TP 35) ───\n")
    L.append(f"  {'Day':<5} {'Sess':>5} {'Win%':>6} {'Dir%':>6} {'Bias':>6} {'Avg':>7} {'Total':>8}")
    L.append("  " + "─" * 48)
    for d in da:
        if d.get('skip'):
            L.append(f"  {d['day']:<5} {d['n']:>5}   — insufficient data")
        else:
            tag = " ← BRACKET" if d['dir_pct'] < 55 else ""
            L.append(f"  {d['day']:<5} {d['n']:>5} {d['wr']:>5.1f}% {d['dir_pct']:>5.1f}% {d['bias']:>6} "
                     f"{d['avg']:>+6.1f} {d['total']:>+7.1f}{tag}")
    if weak_days:
        L.append(f"\n  ★ WEAK DIRECTION DAYS: {', '.join(weak_days)}")

    # --- Entry Offset Optimisation (weak days) ---
    L.append(f"\n─── OFFSET OPTIMISATION — WEAK DAYS ({', '.join(weak_days)}) ───\n")
    L.append(f"  {'Off':>4} {'TP':>4} {'Trig':>5} {'Win%':>6} {'Whip%':>6} {'Avg':>7} {'Total':>8}")
    L.append("  " + "─" * 46)
    top = sorted(opts_weak, key=lambda x: x.get('total',0), reverse=True)[:15]
    for r in top:
        star = " ★" if best_p and r['off'] == best_p['off'] and r['tp'] == best_p['tp'] else ""
        L.append(f"  +{r['off']:>2}  {r['tp']:>3}  {r['trig']:>4}  {r['wr']:>5.1f}% {r['whip_r']:>5.1f}% "
                 f"{r['avg']:>+6.1f} {r['total']:>+7.1f}{star}")
    if best_p:
        L.append(f"\n  ★ BEST: +{best_p['off']}/-{best_p['off']} TP {best_p['tp']} "
                 f"({best_p['wr']:.1f}% win, {best_p['total']:+.1f} pips)")

    # --- All-days comparison ---
    if opts_all:
        L.append(f"\n─── OFFSET OPTIMISATION — ALL DAYS (comparison) ───\n")
        L.append(f"  {'Off':>4} {'TP':>4} {'Trig':>5} {'Win%':>6} {'Avg':>7} {'Total':>8}")
        L.append("  " + "─" * 42)
        top_all = sorted(opts_all, key=lambda x: x.get('total',0), reverse=True)[:10]
        for r in top_all:
            L.append(f"  +{r['off']:>2}  {r['tp']:>3}  {r['trig']:>4}  {r['wr']:>5.1f}% "
                     f"{r['avg']:>+6.1f} {r['total']:>+7.1f}")

    # --- Side Analysis ---
    L.append("\n─── SIDE ANALYSIS (buy vs sell) ───\n")
    for side_name, sd in [('BUY', sides['buy']), ('SELL', sides['sell'])]:
        if sd['n'] == 0:
            L.append(f"  {side_name}: No trades")
        else:
            L.append(f"  {side_name}: {sd['n']} trades | {sd['wr']:.1f}% win | "
                     f"avg {sd['avg']:+.1f} pips | total {sd['total']:+.1f} pips")

    # --- Time to Trigger ---
    if ttf:
        L.append(f"\n─── TIME TO TRIGGER ───\n")
        L.append(f"  Median: {ttf['median_hours']:.0f} hours after London open")
        L.append(f"  25th percentile: {ttf['p25_bars']:.0f}h | 75th: {ttf['p75_bars']:.0f}h")

    # --- Compression ---
    L.append("\n─── COMPRESSION RATIO (Asian / prev day range) ───\n")
    if 'error' in comp:
        L.append(f"  {comp['error']}")
    else:
        L.append(f"  Mean: {comp['mean']}%  Median: {comp['median']}%  Character: {comp['char']}")

    # --- FINAL PARAMETER CARD ---
    L.append("\n" + "=" * w)
    L.append(f"  ★★★ RECOMMENDED PARAMETERS — {pair_name} ★★★")
    L.append("=" * w + "\n")

    # Use adjacent sweet spot if available and better, else single band
    use_band = adj_sweet if adj_sweet and adj_sweet['total'] > (sweet['total'] if sweet else 0) else sweet
    if use_band:
        L.append(f"  Range Filter:     {use_band['band']} pips")
    else:
        L.append(f"  Range Filter:     INSUFFICIENT DATA")

    if best_p:
        L.append(f"  Entry Offset:     +{best_p['off']}/-{best_p['off']} pips")
        L.append(f"  Take Profit:      {best_p['tp']} pips")
        L.append(f"  Win Rate:         {best_p['wr']:.1f}%")
        L.append(f"  Whipsaw Rate:     {best_p['whip_r']:.1f}%")
    else:
        L.append(f"  Entry/TP:         INSUFFICIENT DATA")

    if weak_days:
        L.append(f"  Trading Days:     {', '.join(weak_days)}")

    if best_p and sessions:
        days_span = (sessions[-1]['date'] - sessions[0]['date']).days
        years = max(days_span / 365, 0.5)
        annual = best_p['total'] / years
        L.append(f"  Est. Annual Pips: ~{round(annual)}")
        L.append(f"  Dataset Span:     {years:.1f} years")

    risk_pips = None
    if use_band and best_p:
        band_parts = use_band['band'].split('-')
        mid_range = (int(band_parts[0]) + int(band_parts[1])) / 2
        risk_pips = mid_range + 2 * best_p['off']
        rr = best_p['tp'] / risk_pips if risk_pips > 0 else 0
        L.append(f"  Avg Risk:         ~{risk_pips:.0f} pips (range + 2× offset)")
        L.append(f"  Risk:Reward:      1:{rr:.2f}")
        breakeven_wr = 1 / (1 + rr) * 100 if rr > 0 else 100
        L.append(f"  Breakeven Win%:   {breakeven_wr:.1f}%")

    L.append(f"\n{'─' * w}")
    L.append(f"  Universal Bracket Engine v1.0")
    L.append(f"  Chief collects · Claude analyses · Tom decides")
    L.append(f"{'─' * w}")

    return "\n".join(L)

# ============================================================
# MAIN ENGINE
# ============================================================

def run_engine(pair_key):
    """Full engine run for a single pair."""
    cfg = PAIR_CONFIG[pair_key]
    pip = cfg['pip']
    name = cfg['name']

    print(f"\n{'='*65}")
    print(f"  UNIVERSAL BRACKET ENGINE — {name}")
    print(f"{'='*65}\n")

    # 1. Fetch data
    print("STEP 1/8: Fetching data...")
    hourly = fetch_hourly(cfg['ticker'])

    # 2. Build sessions
    print("STEP 2/8: Building sessions...")
    sessions = build_sessions(hourly, pip)
    print(f"  {len(sessions)} valid sessions")

    # 3. Range profile
    print("STEP 3/8: Range profiling...")
    rp = range_profile(sessions)

    # 4. Range band analysis
    print("STEP 4/8: Range band analysis...")
    rba = range_band_analysis(sessions, pip)
    sweet = find_sweet_spot(rba)
    adj_sweet = find_adjacent_sweet(rba)
    
    # Determine working range
    best_rng = adj_sweet if adj_sweet and adj_sweet['total'] > (sweet['total'] if sweet else 0) else sweet
    if best_rng:
        parts = best_rng['band'].split('-')
        rng_lo, rng_hi = int(parts[0]), int(parts[1])
    else:
        rng_lo, rng_hi = int(rp['p25']), int(rp['p75'])
    print(f"  Working range: {rng_lo}-{rng_hi} pips")

    # 5. Day analysis
    print("STEP 5/8: Day of week analysis...")
    da = day_analysis(sessions, pip, rng_lo=rng_lo, rng_hi=rng_hi)
    weak = find_weak_days(da)
    print(f"  Weak direction days: {weak}")

    # 6. Offset optimisation
    print("STEP 6/8: Offset optimisation...")
    opts_weak = offset_optimisation(sessions, pip, rng_lo=rng_lo, rng_hi=rng_hi, day_filter=weak)
    opts_all  = offset_optimisation(sessions, pip, rng_lo=rng_lo, rng_hi=rng_hi)
    best_p = find_best_params(opts_weak)
    if best_p:
        print(f"  Best: +{best_p['off']}/-{best_p['off']} TP{best_p['tp']} → {best_p['total']:+.1f} pips")

    # 7. Additional analyses
    print("STEP 7/8: Side analysis + compression + time-to-trigger...")
    use_off = best_p['off'] if best_p else 5
    use_tp = best_p['tp'] if best_p else 35
    sides = side_analysis(sessions, pip, offset=use_off, tp=use_tp, rng_lo=rng_lo, rng_hi=rng_hi)
    comp = compression_analysis(sessions, pip)
    ttf = time_to_trigger(sessions, pip, offset=use_off, rng_lo=rng_lo, rng_hi=rng_hi)

    # 8. Generate card
    print("STEP 8/8: Generating parameter card...")
    card = format_card(name, sessions, rp, rba, da, opts_weak, opts_all,
                       comp, sides, ttf, sweet, adj_sweet, weak, best_p)

    # Save outputs
    txt_path = f"/agent/home/bracket_params_{pair_key.lower()}.txt"
    json_path = f"/agent/home/bracket_params_{pair_key.lower()}.json"

    with open(txt_path, 'w') as f:
        f.write(card)

    json_out = {
        'pair': pair_key, 'name': name,
        'generated': datetime.now().isoformat(),
        'sessions': len(sessions),
        'period': f"{sessions[0]['date']} → {sessions[-1]['date']}" if sessions else None,
        'range_profile': rp,
        'sweet_spot': sweet if sweet and not sweet.get('skip') else None,
        'adjacent_sweet': adj_sweet,
        'weak_days': weak,
        'best_params': {k: v for k, v in best_p.items() if k != 'score'} if best_p else None,
        'compression': comp,
        'side_analysis': sides,
        'time_to_trigger': ttf,
        'range_bands': [r for r in rba if not r.get('skip')],
        'day_results': [d for d in da if not d.get('skip')],
    }
    with open(json_path, 'w') as f:
        json.dump(json_out, f, indent=2, default=str)

    print(f"\n  ✅ Saved: {txt_path}")
    print(f"  ✅ Saved: {json_path}")

    return card


def main():
    pairs = sys.argv[1:] if len(sys.argv) > 1 else ['EURUSD']
    for pair in pairs:
        pair = pair.upper().replace('/', '').replace('-', '')
        if pair not in PAIR_CONFIG:
            print(f"Unknown pair: {pair}. Available: {', '.join(PAIR_CONFIG.keys())}")
            continue
        card = run_engine(pair)
        if card:
            print("\n" + card)


if __name__ == '__main__':
    main()
