#!/usr/bin/env python3
"""
Parameter optimizer for ORB + optional GEX filter logic.

This script approximates:
  - 30-minute-opening-range-breakout-beginner-auto-orb-strategy.pine

It grid-searches parameter sets on 15m and 30m bars and ranks by net PnL
(with drawdown and win-rate in output for sanity checking).

Required CSV columns (case-insensitive):
  - time (or timestamp/datetime/date), open, high, low, close

Optional columns used for GEX filtering/exits:
  - net_gex, call_wall, put_wall

Example:
python pinescript-agents/tools/optimize_orb_gex_strategy.py ^
  --csv pinescript-agents/projects/btc_3m.csv ^
  --timeframes 15,30 ^
  --top 25 ^
  --out pinescript-agents/projects/analysis/orb_gex_optimization.csv
"""

from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

import numpy as np
import pandas as pd


def parse_int_list(text: str) -> List[int]:
    return [int(x.strip()) for x in text.split(",") if x.strip()]


def parse_float_list(text: str) -> List[float]:
    return [float(x.strip()) for x in text.split(",") if x.strip()]


def parse_bool_list(text: str) -> List[bool]:
    truth = {"1", "true", "t", "yes", "y"}
    falsy = {"0", "false", "f", "no", "n"}
    out: List[bool] = []
    for raw in text.split(","):
        token = raw.strip().lower()
        if not token:
            continue
        if token in truth:
            out.append(True)
        elif token in falsy:
            out.append(False)
        else:
            raise ValueError(f"Invalid bool token: {raw}")
    return out


def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    colmap = {c: c.strip().lower() for c in df.columns}
    df = df.rename(columns=colmap)

    time_col = next((c for c in ["time", "timestamp", "datetime", "date"] if c in df.columns), None)
    if not time_col:
        raise ValueError("CSV must contain one of: time, timestamp, datetime, date")

    req = ["open", "high", "low", "close"]
    missing = [c for c in req if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing required OHLC columns: {missing}")

    ts_num = pd.to_numeric(df[time_col], errors="coerce")
    if ts_num.notna().any():
        unit = "ms" if ts_num.dropna().median() > 1e11 else "s"
        parsed = pd.to_datetime(ts_num, unit=unit, errors="coerce", utc=True)
        df["time"] = parsed.fillna(pd.to_datetime(df[time_col], errors="coerce", utc=True))
    else:
        df["time"] = pd.to_datetime(df[time_col], errors="coerce", utc=True)

    for c in ["open", "high", "low", "close", "volume", "net_gex", "call_wall", "put_wall"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    keep = ["time", "open", "high", "low", "close", "volume", "net_gex", "call_wall", "put_wall"]
    for c in keep:
        if c not in df.columns:
            df[c] = np.nan

    df = df.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time").reset_index(drop=True)
    if len(df) < 300:
        raise ValueError("Need at least 300 rows of source data.")
    return df[keep]


def resample_ohlc(df: pd.DataFrame, tf_minutes: int) -> pd.DataFrame:
    rule = f"{tf_minutes}min"
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "net_gex": "last",
        "call_wall": "last",
        "put_wall": "last",
    }
    out = (
        df.set_index("time")
        .resample(rule, label="right", closed="right")
        .agg(agg)
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )
    return out


@dataclass
class Params:
    fast_ema: int
    slow_ema: int
    orb_minutes: int
    require_retest: bool
    risk_pct: float
    tp1_r: float
    tp2_r: float
    move_stop_to_be: bool
    use_gex_filter: bool
    use_gex_exit: bool
    gex_band_pts: float
    contracts: int


@dataclass
class Stats:
    timeframe_min: int
    net_pnl: float
    gross_profit: float
    gross_loss: float
    trades: int
    wins: int
    losses: int
    win_rate: float
    max_drawdown: float
    pnl_per_trade: float
    params: Params


def max_drawdown(equity_curve: np.ndarray) -> float:
    if equity_curve.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity_curve)
    dd = equity_curve - peak
    return float(dd.min())


def is_in_session(ts_utc: pd.Timestamp, session: str, tz_name: str) -> bool:
    local_ts = ts_utc.tz_convert(tz_name)
    hhmm = local_ts.hour * 100 + local_ts.minute
    start, end = session.split("-")
    start_i = int(start)
    end_i = int(end)
    return start_i <= hhmm < end_i


def session_day_key(ts_utc: pd.Timestamp, tz_name: str) -> int:
    local_ts = ts_utc.tz_convert(tz_name)
    return local_ts.year * 10000 + local_ts.month * 100 + local_ts.day


def backtest(df: pd.DataFrame, p: Params, session: str, session_tz: str, timeframe_min: int) -> Stats:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    net_gex = df["net_gex"]
    call_wall = df["call_wall"]
    put_wall = df["put_wall"]

    fast_ema = close.ewm(span=p.fast_ema, adjust=False, min_periods=p.fast_ema).mean()
    slow_ema = close.ewm(span=p.slow_ema, adjust=False, min_periods=p.slow_ema).mean()

    position = 0  # 1 long, -1 short, 0 flat
    remaining_qty = 0.0
    entry_price = 0.0
    stop_price = np.nan
    tp1_price = np.nan
    tp2_price = np.nan
    tp1_done = False
    traded_this_session = False

    current_session_key = None
    orb_high = np.nan
    orb_low = np.nan
    orb_locked = False
    orb_end_ts = None

    gross_profit = 0.0
    gross_loss = 0.0
    trades = 0
    wins = 0
    losses = 0

    equity = 0.0
    equity_curve: List[float] = []

    def book(pnl: float) -> None:
        nonlocal equity, gross_profit, gross_loss
        equity += pnl
        if pnl >= 0:
            gross_profit += pnl
        else:
            gross_loss += pnl

    for i in range(1, len(df)):
        ts = df.at[i, "time"]
        prev_ts = df.at[i - 1, "time"]

        in_sess = is_in_session(ts, session, session_tz)
        prev_in_sess = is_in_session(prev_ts, session, session_tz)
        new_session = in_sess and not prev_in_sess
        sess_end = (not in_sess) and prev_in_sess

        if new_session:
            traded_this_session = False
            orb_locked = False
            orb_high = high.iat[i]
            orb_low = low.iat[i]
            current_session_key = session_day_key(ts, session_tz)
            orb_end_ts = ts + pd.Timedelta(minutes=p.orb_minutes)

        if in_sess and not orb_locked and orb_end_ts is not None:
            in_orb_window = ts < orb_end_ts
            if in_orb_window:
                orb_high = high.iat[i] if np.isnan(orb_high) else max(orb_high, high.iat[i])
                orb_low = low.iat[i] if np.isnan(orb_low) else min(orb_low, low.iat[i])
            else:
                orb_locked = True

        if sess_end:
            orb_locked = False

        c = close.iat[i]
        h = high.iat[i]
        l = low.iat[i]
        f = fast_ema.iat[i]
        s = slow_ema.iat[i]
        if np.isnan(f) or np.isnan(s):
            equity_curve.append(equity)
            continue

        g = net_gex.iat[i]
        cw = call_wall.iat[i]
        pw = put_wall.iat[i]
        near_res = False
        near_sup = False
        if not np.isnan(cw):
            near_res = (cw >= c) and ((cw - c) <= p.gex_band_pts)
        if not np.isnan(pw):
            near_sup = (pw <= c) and ((c - pw) <= p.gex_band_pts)

        gex_filter_active = p.use_gex_filter and (not np.isnan(g))
        gex_exit_active = p.use_gex_exit and (not np.isnan(g))
        allow_long_gex = (not gex_filter_active) or (g > 0 and not near_res)
        allow_short_gex = (not gex_filter_active) or (g <= 0 and not near_sup)

        trend_long = f > s
        trend_short = f < s
        long_breakout = orb_locked and trend_long and (high.iat[i - 1] <= orb_high) and (h > orb_high)
        short_breakout = orb_locked and trend_short and (low.iat[i - 1] >= orb_low) and (l < orb_low)
        retest_long = (l <= orb_high) and (c > orb_high)
        retest_short = (h >= orb_low) and (c < orb_low)

        long_trigger = long_breakout and (not p.require_retest or retest_long) and allow_long_gex
        short_trigger = short_breakout and (not p.require_retest or retest_short) and allow_short_gex
        can_trade = in_sess and orb_locked and (not traded_this_session) and (position == 0)

        if can_trade and long_trigger:
            position = 1
            entry_price = c
            remaining_qty = float(p.contracts)
            risk = entry_price * (p.risk_pct / 100.0)
            stop_price = entry_price - risk
            tp1_price = entry_price + risk * p.tp1_r
            tp2_price = entry_price + risk * p.tp2_r
            tp1_done = False
            traded_this_session = True
            trades += 1
        elif can_trade and short_trigger:
            position = -1
            entry_price = c
            remaining_qty = float(p.contracts)
            risk = entry_price * (p.risk_pct / 100.0)
            stop_price = entry_price + risk
            tp1_price = entry_price - risk * p.tp1_r
            tp2_price = entry_price - risk * p.tp2_r
            tp1_done = False
            traded_this_session = True
            trades += 1

        # Manage exits
        if position == 1 and remaining_qty > 0:
            stopped = l <= stop_price
            if stopped:
                pnl = (stop_price - entry_price) * remaining_qty
                book(pnl)
                if pnl >= 0:
                    wins += 1
                else:
                    losses += 1
                position = 0
                remaining_qty = 0.0
            else:
                if (not tp1_done) and (h >= tp1_price):
                    q = remaining_qty * 0.5
                    pnl = (tp1_price - entry_price) * q
                    book(pnl)
                    remaining_qty -= q
                    tp1_done = True
                    if p.move_stop_to_be:
                        stop_price = entry_price
                if remaining_qty > 0 and h >= tp2_price:
                    pnl = (tp2_price - entry_price) * remaining_qty
                    book(pnl)
                    wins += 1 if pnl >= 0 else 0
                    losses += 1 if pnl < 0 else 0
                    position = 0
                    remaining_qty = 0.0
                elif remaining_qty > 0 and gex_exit_active and near_res:
                    pnl = (c - entry_price) * remaining_qty
                    book(pnl)
                    wins += 1 if pnl >= 0 else 0
                    losses += 1 if pnl < 0 else 0
                    position = 0
                    remaining_qty = 0.0

        if position == -1 and remaining_qty > 0:
            stopped = h >= stop_price
            if stopped:
                pnl = (entry_price - stop_price) * remaining_qty
                book(pnl)
                if pnl >= 0:
                    wins += 1
                else:
                    losses += 1
                position = 0
                remaining_qty = 0.0
            else:
                if (not tp1_done) and (l <= tp1_price):
                    q = remaining_qty * 0.5
                    pnl = (entry_price - tp1_price) * q
                    book(pnl)
                    remaining_qty -= q
                    tp1_done = True
                    if p.move_stop_to_be:
                        stop_price = entry_price
                if remaining_qty > 0 and l <= tp2_price:
                    pnl = (entry_price - tp2_price) * remaining_qty
                    book(pnl)
                    wins += 1 if pnl >= 0 else 0
                    losses += 1 if pnl < 0 else 0
                    position = 0
                    remaining_qty = 0.0
                elif remaining_qty > 0 and gex_exit_active and near_sup:
                    pnl = (entry_price - c) * remaining_qty
                    book(pnl)
                    wins += 1 if pnl >= 0 else 0
                    losses += 1 if pnl < 0 else 0
                    position = 0
                    remaining_qty = 0.0

        equity_curve.append(equity)

    # Flat final open position at last close
    if position != 0 and remaining_qty > 0:
        last_close = close.iat[-1]
        pnl = (last_close - entry_price) * remaining_qty if position == 1 else (entry_price - last_close) * remaining_qty
        equity += pnl
        if pnl >= 0:
            gross_profit += pnl
            wins += 1
        else:
            gross_loss += pnl
            losses += 1

    wr = (wins / trades * 100.0) if trades > 0 else 0.0
    pnl_per_trade = (equity / trades) if trades > 0 else 0.0
    mdd = max_drawdown(np.asarray(equity_curve, dtype=float))

    return Stats(
        timeframe_min=timeframe_min,
        net_pnl=float(equity),
        gross_profit=float(gross_profit),
        gross_loss=float(gross_loss),
        trades=int(trades),
        wins=int(wins),
        losses=int(losses),
        win_rate=float(wr),
        max_drawdown=float(mdd),
        pnl_per_trade=float(pnl_per_trade),
        params=p,
    )


def build_grid(args: argparse.Namespace) -> Iterable[Params]:
    for (
        fast_ema,
        slow_ema,
        orb_minutes,
        require_retest,
        risk_pct,
        tp1_r,
        tp2_r,
        move_stop_to_be,
        use_gex_filter,
        use_gex_exit,
        gex_band_pts,
    ) in itertools.product(
        parse_int_list(args.fast_ema_values),
        parse_int_list(args.slow_ema_values),
        parse_int_list(args.orb_minutes_values),
        parse_bool_list(args.require_retest_values),
        parse_float_list(args.risk_pct_values),
        parse_float_list(args.tp1_r_values),
        parse_float_list(args.tp2_r_values),
        parse_bool_list(args.move_to_be_values),
        parse_bool_list(args.use_gex_filter_values),
        parse_bool_list(args.use_gex_exit_values),
        parse_float_list(args.gex_band_values),
    ):
        if fast_ema >= slow_ema:
            continue
        if tp2_r < tp1_r:
            continue
        if risk_pct <= 0:
            continue
        yield Params(
            fast_ema=fast_ema,
            slow_ema=slow_ema,
            orb_minutes=orb_minutes,
            require_retest=require_retest,
            risk_pct=risk_pct,
            tp1_r=tp1_r,
            tp2_r=tp2_r,
            move_stop_to_be=move_stop_to_be,
            use_gex_filter=use_gex_filter,
            use_gex_exit=use_gex_exit,
            gex_band_pts=gex_band_pts,
            contracts=args.contracts,
        )


def main() -> None:
    p = argparse.ArgumentParser(description="Optimize ORB + GEX params on 15m/30m data.")
    p.add_argument("--csv", required=True, help="Input OHLC(+optional GEX) CSV.")
    p.add_argument("--timeframes", default="15,30", help="Comma-separated minute timeframes, e.g. 15,30")
    p.add_argument("--session", default="0930-1600", help="Session window in HHMM-HHMM.")
    p.add_argument("--session-tz", default="America/New_York", help="Session timezone.")
    p.add_argument("--contracts", type=int, default=1, help="Contracts per trade.")
    p.add_argument("--top", type=int, default=25, help="Top rows to print.")
    p.add_argument("--out", default="orb_gex_optimization_results.csv", help="Output CSV path.")

    # Grid defaults intentionally compact so runtime stays practical.
    p.add_argument("--fast-ema-values", default="8,9,12")
    p.add_argument("--slow-ema-values", default="20,21,30")
    p.add_argument("--orb-minutes-values", default="20,30,45")
    p.add_argument("--require-retest-values", default="false,true")
    p.add_argument("--risk-pct-values", default="0.25,0.35,0.5")
    p.add_argument("--tp1-r-values", default="1.0,1.25")
    p.add_argument("--tp2-r-values", default="1.75,2.0,2.5")
    p.add_argument("--move-to-be-values", default="false,true")
    p.add_argument("--use-gex-filter-values", default="false,true")
    p.add_argument("--use-gex-exit-values", default="false,true")
    p.add_argument("--gex-band-values", default="2,10,20")
    args = p.parse_args()

    df = normalize_df(pd.read_csv(args.csv))
    tfs = parse_int_list(args.timeframes)
    grid = list(build_grid(args))
    if not grid:
        raise SystemExit("No valid parameter combinations.")

    results: List[Stats] = []
    total = len(grid) * len(tfs)
    done = 0

    for tf in tfs:
        tf_df = resample_ohlc(df, tf)
        if len(tf_df) < 200:
            print(f"Skipping {tf}m: not enough bars after resample ({len(tf_df)})")
            continue
        for params in grid:
            res = backtest(tf_df, params, args.session, args.session_tz, tf)
            results.append(res)
            done += 1
            if done % 200 == 0 or done == total:
                print(f"Progress: {done}/{total}")

    if not results:
        raise SystemExit("No results generated.")

    rows = []
    for r in results:
        row = {
            "timeframe_min": r.timeframe_min,
            "net_pnl": r.net_pnl,
            "gross_profit": r.gross_profit,
            "gross_loss": r.gross_loss,
            "trades": r.trades,
            "wins": r.wins,
            "losses": r.losses,
            "win_rate": r.win_rate,
            "max_drawdown": r.max_drawdown,
            "pnl_per_trade": r.pnl_per_trade,
            "fast_ema": r.params.fast_ema,
            "slow_ema": r.params.slow_ema,
            "orb_minutes": r.params.orb_minutes,
            "require_retest": r.params.require_retest,
            "risk_pct": r.params.risk_pct,
            "tp1_r": r.params.tp1_r,
            "tp2_r": r.params.tp2_r,
            "move_stop_to_be": r.params.move_stop_to_be,
            "use_gex_filter": r.params.use_gex_filter,
            "use_gex_exit": r.params.use_gex_exit,
            "gex_band_pts": r.params.gex_band_pts,
            "contracts": r.params.contracts,
        }
        rows.append(row)

    out_df = pd.DataFrame(rows).sort_values(["net_pnl", "max_drawdown", "win_rate"], ascending=[False, False, False])
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False)

    print(f"\nSaved full results: {out_path}")
    print("\nTop overall:")
    print(out_df.head(args.top).to_string(index=False))

    for tf in sorted(out_df["timeframe_min"].unique()):
        print(f"\nTop {args.top} for {tf}m:")
        print(out_df[out_df["timeframe_min"] == tf].head(args.top).to_string(index=False))


if __name__ == "__main__":
    main()

