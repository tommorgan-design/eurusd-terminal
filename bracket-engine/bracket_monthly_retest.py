#!/usr/bin/env python3
"""
BRACKET MONTHLY RETEST v1.0
Re-runs the Universal Bracket Engine on current data, compares to live parameters,
and produces a drift report highlighting any parameter changes needed.

Run: uv run --with yfinance,pandas,numpy python3 bracket_monthly_retest.py
"""

import json
import os
import sys
import importlib.util
from datetime import datetime

# ─── LIVE PARAMETERS (current trading parameters) ───
LIVE_PARAMS = {
    "EURUSD": {
        "pair": "EUR/USD",
        "ticker": "EURUSD=X",
        "pip": 0.0001,
        "range_min": 25,
        "range_max": 40,
        "entry_offset": 5,
        "take_profit": 35,
        "trading_days": ["Wed", "Thu"],          # short names to match engine session['day']
        "trading_days_full": ["Wednesday", "Thursday"],  # for display
        "baseline_win_rate": 60.0,
        "baseline_2yr_pips": 825,
        "last_updated": "2026-05-09"
    },
    "GBPUSD": {
        "pair": "GBP/USD",
        "ticker": "GBPUSD=X",
        "pip": 0.0001,
        "range_min": 20,
        "range_max": 25,
        "entry_offset": 7,
        "take_profit": 35,
        "trading_days": ["Wed", "Thu"],
        "trading_days_full": ["Wednesday", "Thursday"],
        "baseline_win_rate": 58.8,
        "baseline_2yr_pips": 655,
        "last_updated": "2026-05-09"
    }
}

# ─── DRIFT THRESHOLDS ───
WIN_RATE_DRIFT_PP = 5.0        # Flag if win rate changes by more than 5 percentage points
PIPS_DRIFT_PCT = 15.0          # Flag if total pips changes by more than 15%


def load_engine():
    """Import the universal bracket engine module."""
    engine_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'universal_bracket_engine.py')
    spec = importlib.util.spec_from_file_location("bracket_engine", engine_path)
    eng = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eng)
    return eng


def retest_pair(eng, pair_key, lp):
    """Run engine analysis for one pair and compare to live parameters."""

    print(f"\n{'='*60}")
    print(f"  RETESTING: {lp['pair']}")
    print(f"{'='*60}")

    pip = lp['pip']

    # 1. Fetch data
    hourly = eng.fetch_hourly(lp['ticker'])
    if hourly is None or len(hourly) < 500:
        return error_result(lp['pair'], f"Insufficient data: {len(hourly) if hourly is not None else 0} rows")

    # 2. Build sessions
    sessions = eng.build_sessions(hourly, pip)
    n_sessions = len(sessions)
    print(f"  Sessions: {n_sessions}")

    if n_sessions < 200:
        return error_result(lp['pair'], f"Only {n_sessions} sessions — need 200+ for reliable stats", "WARNING")

    # 3. Range profile — find what the engine now recommends as sweet spot
    rp = eng.range_profile(sessions)
    rba = eng.range_band_analysis(sessions, pip, offset=lp['entry_offset'], tp=lp['take_profit'])
    sweet = eng.find_sweet_spot(rba)
    adj_sweet = eng.find_adjacent_sweet(rba)

    # Determine engine's recommended range (both return 'band' as "lo-hi" string)
    if adj_sweet and not adj_sweet.get('skip') and adj_sweet.get('band'):
        parts = adj_sweet['band'].split('-')
        new_range_min, new_range_max = int(parts[0]), int(parts[1])
    elif sweet and not sweet.get('skip') and sweet.get('band'):
        parts = sweet['band'].split('-')
        new_range_min, new_range_max = int(parts[0]), int(parts[1])
    else:
        new_range_min = int(rp.get('p25', lp['range_min']))
        new_range_max = int(rp.get('p75', lp['range_max']))

    # 4. Day analysis — check if weak days have shifted
    da = eng.day_analysis(sessions, pip, rng_lo=lp['range_min'], rng_hi=lp['range_max'])
    new_weak_days = eng.find_weak_days(da)

    # 5. Offset optimisation on weak days with LIVE range filter
    opts_weak = eng.offset_optimisation(sessions, pip,
                                         rng_lo=lp['range_min'], rng_hi=lp['range_max'],
                                         day_filter=lp['trading_days'])
    new_best = eng.find_best_params(opts_weak)

    new_offset = new_best['off'] if new_best else lp['entry_offset']
    new_tp = new_best['tp'] if new_best else lp['take_profit']

    # 6. Simulate CURRENT LIVE parameters on latest data to get actual performance
    # Engine sessions use: 'day' (short: Mon/Tue/Wed...), 'a_range' (pips), sim_bracket()
    live_sessions = [s for s in sessions
                     if s.get('day') in lp['trading_days']
                     and lp['range_min'] <= s.get('a_range', 0) <= lp['range_max']]

    wins = losses = whipsaws = 0
    total_pips = 0.0

    for s in live_sessions:
        result = eng.sim_bracket(s, lp['entry_offset'], lp['take_profit'], pip)
        outcome = result.get('out', 'none')
        if outcome == 'win':
            wins += 1
            total_pips += lp['take_profit']
        elif outcome == 'loss':
            losses += 1
            risk = s.get('a_range', 30) + 2 * lp['entry_offset']
            total_pips -= risk
        elif outcome == 'whipsaw':
            whipsaws += 1
            risk = s.get('a_range', 30) + 2 * lp['entry_offset']
            total_pips -= risk

    valid = wins + losses
    current_wr = (wins / valid * 100) if valid > 0 else 0

    # 7. Build drift flags
    drift_flags = []

    # Range drift
    if new_range_min != lp['range_min'] or new_range_max != lp['range_max']:
        shift = abs(new_range_min - lp['range_min']) + abs(new_range_max - lp['range_max'])
        drift_flags.append({
            "param": "Range Filter",
            "live": f"{lp['range_min']}-{lp['range_max']} pips",
            "new": f"{new_range_min}-{new_range_max} pips",
            "severity": "HIGH" if shift > 10 else "MODERATE"
        })

    # Offset drift
    if new_offset != lp['entry_offset']:
        drift_flags.append({
            "param": "Entry Offset",
            "live": f"+{lp['entry_offset']}/-{lp['entry_offset']}",
            "new": f"+{new_offset}/-{new_offset}",
            "severity": "HIGH" if abs(new_offset - lp['entry_offset']) > 3 else "MODERATE"
        })

    # TP drift
    if new_tp != lp['take_profit']:
        drift_flags.append({
            "param": "Take Profit",
            "live": f"{lp['take_profit']} pips",
            "new": f"{new_tp} pips",
            "severity": "HIGH" if abs(new_tp - lp['take_profit']) > 5 else "MODERATE"
        })

    # Win rate drift
    wr_delta = current_wr - lp['baseline_win_rate']
    if abs(wr_delta) > WIN_RATE_DRIFT_PP:
        drift_flags.append({
            "param": "Win Rate",
            "live": f"{lp['baseline_win_rate']:.1f}%",
            "new": f"{current_wr:.1f}% ({'+' if wr_delta > 0 else ''}{wr_delta:.1f}pp)",
            "severity": "HIGH" if abs(wr_delta) > 10 else "MODERATE"
        })

    # Total pips drift
    if lp['baseline_2yr_pips'] != 0:
        pips_delta_pct = (total_pips - lp['baseline_2yr_pips']) / lp['baseline_2yr_pips'] * 100
        if abs(pips_delta_pct) > PIPS_DRIFT_PCT:
            drift_flags.append({
                "param": "Total Pips",
                "live": f"{lp['baseline_2yr_pips']}",
                "new": f"{total_pips:.0f} ({'+' if pips_delta_pct > 0 else ''}{pips_delta_pct:.1f}%)",
                "severity": "HIGH" if abs(pips_delta_pct) > 25 else "MODERATE"
            })

    # Day character shift — da entries use 'day' key with short names
    day_shifts = []
    for d in da:
        if d.get('skip'):
            continue
        dn = d.get('day', '')
        dm = d.get('dir_pct', 50)
        if dn in lp['trading_days'] and dm > 55:
            day_shifts.append(f"{dn} now {dm:.0f}% directional (was weak)")
        elif dn not in lp['trading_days'] and dm < 45:
            day_shifts.append(f"{dn} now {dm:.0f}% directional (new bracket candidate)")

    if day_shifts:
        drift_flags.append({
            "param": "Day Character",
            "live": ", ".join(lp['trading_days']),
            "new": "; ".join(day_shifts),
            "severity": "MODERATE"
        })

    status = ("NO DRIFT" if not drift_flags
              else "REVIEW NEEDED" if any(f['severity'] == 'HIGH' for f in drift_flags)
              else "MINOR DRIFT")

    return {
        "pair": lp['pair'],
        "status": status,
        "sessions_analysed": n_sessions,
        "qualifying_sessions": len(live_sessions),
        "trades": valid,
        "whipsaws": whipsaws,
        "current_live_params": {
            "range": f"{lp['range_min']}-{lp['range_max']}",
            "offset": lp['entry_offset'],
            "tp": lp['take_profit'],
            "days": lp['trading_days'],
            "days_full": lp.get('trading_days_full', lp['trading_days'])
        },
        "engine_recommended": {
            "range": f"{new_range_min}-{new_range_max}",
            "offset": new_offset,
            "tp": new_tp,
            "weak_days": new_weak_days
        },
        "performance_on_live_params": {
            "win_rate": round(current_wr, 1),
            "total_pips": round(total_pips, 1),
            "wins": wins,
            "losses": losses,
            "whipsaws": whipsaws
        },
        "drift_flags": drift_flags,
        "retest_date": datetime.utcnow().strftime('%Y-%m-%d')
    }


def error_result(pair, message, status="ERROR"):
    return {"pair": pair, "status": status, "message": message,
            "drift_flags": [], "retest_date": datetime.utcnow().strftime('%Y-%m-%d')}


def generate_report(results):
    """Generate a plain-English drift report."""
    report_date = datetime.utcnow().strftime('%Y-%m-%d')

    lines = [
        "=" * 60,
        f"  BRACKET MONTHLY RETEST REPORT — {report_date}",
        "=" * 60, ""
    ]

    any_high = False

    for r in results:
        pair = r['pair']
        status = r['status']
        emoji = {"NO DRIFT": "✅", "MINOR DRIFT": "⚡", "REVIEW NEEDED": "🔴",
                 "ERROR": "❌", "WARNING": "⚠️"}.get(status, "?")

        lines += [f"─── {pair} ── {emoji} {status} ───", ""]

        if status in ("ERROR", "WARNING"):
            lines += [f"  {r.get('message', 'Unknown')}", ""]
            continue

        lp = r['current_live_params']
        perf = r.get('performance_on_live_params', {})
        rec = r.get('engine_recommended', {})

        lines.append(f"  Sessions:   {r['sessions_analysed']}  |  Qualifying: {r['qualifying_sessions']}  |  Trades: {r.get('trades', '?')}")
        days_display = lp.get('days_full', lp['days'])
        lines.append(f"  LIVE:       Range {lp['range']}, Offset +{lp['offset']}, TP {lp['tp']}, Days: {', '.join(days_display)}")
        lines.append(f"  PERF:       Win {perf.get('win_rate', '?')}%, Pips {perf.get('total_pips', '?')}, W/L/WS {perf.get('wins', '?')}/{perf.get('losses', '?')}/{perf.get('whipsaws', '?')}")
        lines.append(f"  ENGINE:     Range {rec.get('range', '?')}, Offset +{rec.get('offset', '?')}, TP {rec.get('tp', '?')}")

        if rec.get('weak_days'):
            lines.append(f"  WEAK DAYS:  {', '.join(rec['weak_days'])}")
        lines.append("")

        flags = r.get('drift_flags', [])
        if flags:
            lines.append("  DRIFT FLAGS:")
            for f in flags:
                icon = "🔴" if f['severity'] == 'HIGH' else "⚡"
                lines.append(f"    {icon} {f['param']}: Live={f['live']} → New={f['new']} [{f['severity']}]")
            lines.append("")
            if any(f['severity'] == 'HIGH' for f in flags):
                any_high = True
        else:
            lines += ["  No drift detected. Parameters remain optimal.", ""]

    lines.append("─" * 60)

    if any_high:
        lines += ["", "⚠️  HIGH SEVERITY DRIFT DETECTED",
                   "   Review before next trading session.",
                   "   Parameters are hypotheses, not laws."]
    else:
        lines += ["", "✅  All parameters within acceptable bounds.",
                   "   No changes needed. Re-run next month."]

    lines += ["", "─" * 60,
              f"Report generated: {report_date}",
              "Chief collects · Claude analyses · Tom decides", ""]

    return "\n".join(lines)


def main():
    eng = load_engine()

    results = []
    for pair_key, params in LIVE_PARAMS.items():
        try:
            result = retest_pair(eng, pair_key, params)
            results.append(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            results.append(error_result(params['pair'], str(e)))

    report = generate_report(results)
    print("\n" + report)

    # Save report — write to /tmp first, then copy to persistent storage
    import shutil
    tmp_report = "/tmp/bracket_retest_report.txt"
    tmp_json = "/tmp/bracket_retest_results.json"

    with open(tmp_report, 'w') as f:
        f.write(report)

    with open(tmp_json, 'w') as f:
        json.dump({"retest_date": datetime.utcnow().strftime('%Y-%m-%d'), "pairs": results},
                  f, indent=2, default=str)

    # Copy to persistent storage
    base = "/agent/home"
    report_path = os.path.join(base, "bracket_retest_report.txt")
    json_path = os.path.join(base, "bracket_retest_results.json")
    try:
        shutil.copy2(tmp_report, report_path)
        shutil.copy2(tmp_json, json_path)
        print(f"Report saved: {report_path}")
        print(f"JSON saved: {json_path}")
    except Exception as e:
        print(f"Persistent save failed ({e}) — files at {tmp_report} and {tmp_json}")
        report_path = tmp_report
        json_path = tmp_json

    return results


if __name__ == "__main__":
    main()
