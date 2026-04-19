#!/usr/bin/env python3
"""
Grid-search optimizer for BTC_tradingview_scalp_strategy.

This script approximates the Pine strategy logic and evaluates many parameter
combinations on OHLCV CSV data to find the highest net PnL settings.

Required CSV columns (case-insensitive):
- open, high, low, close
Optional:
- time / timestamp / datetime

Example:
python BTC_tradingview_scalp_strategy_optimizer.py \
  --csv btc_3m.csv \
  --top 20 \
  --out btc_scalp_optimization_results.csv
"""

from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Sequence

import numpy as np
import pandas as pd


@dataclass
class Params:
    fast_ema: int
    slow_ema: int
    rsi_len: int
    rsi_midline: float
    require_pullback_color: bool
    use_rsi_filter: bool
    pip_size: float
    max_entry_distance_pips: float
    tp1_pips: float
    tp2_pips: float
    stop_loss_pips: float
    tp1_close_pct: float
    exit_runner_on_momentum_flip: bool
    contracts_per_trade: int
    allow_longs: bool
    allow_shorts: bool


@dataclass
class Result:
    net_pnl: float
    gross_profit: float
    gross_loss: float
    trades: int
    wins: int
    losses: int
    win_rate: float
    max_drawdown: float
    sharpe_like: float
    params: Params


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    colmap = {c: c.strip().lower() for c in df.columns}
    df = df.rename(columns=colmap)

    required = {"open", "high", "low", "close"}
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}")

    time_candidates = ["time", "timestamp", "datetime", "date"]
    tcol = next((c for c in time_candidates if c in df.columns), None)
    if tcol:
        df[tcol] = pd.to_datetime(df[tcol], errors="coerce", utc=True)
        df = df.sort_values(tcol).reset_index(drop=True)

    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if len(df) < 200:
        raise ValueError("Need at least 200 rows for stable EMA/RSI backtest.")
    return df


def rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def max_drawdown(equity_curve: np.ndarray) -> float:
    if equity_curve.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity_curve)
    dd = equity_curve - peak
    return float(dd.min())


def parse_int_list(text: str) -> List[int]:
    return [int(x.strip()) for x in text.split(",") if x.strip()]


def parse_float_list(text: str) -> List[float]:
    return [float(x.strip()) for x in text.split(",") if x.strip()]


def parse_bool_list(text: str) -> List[bool]:
    truth = {"1", "true", "t", "yes", "y"}
    falsy = {"0", "false", "f", "no", "n"}
    out: List[bool] = []
    for raw in text.split(","):
        x = raw.strip().lower()
        if not x:
            continue
        if x in truth:
            out.append(True)
        elif x in falsy:
            out.append(False)
        else:
            raise ValueError(f"Invalid bool token: {raw}")
    return out


def build_grid(args: argparse.Namespace) -> List[Params]:
    grid = []

    for (
        fast_ema,
        slow_ema,
        rsi_len,
        rsi_midline,
        require_pullback_color,
        use_rsi_filter,
        max_entry_distance_pips,
        tp1_pips,
        tp2_pips,
        stop_loss_pips,
        tp1_close_pct,
        exit_runner_on_momentum_flip,
    ) in itertools.product(
        parse_int_list(args.fast_ema_values),
        parse_int_list(args.slow_ema_values),
        parse_int_list(args.rsi_len_values),
        parse_float_list(args.rsi_midline_values),
        parse_bool_list(args.require_pullback_color_values),
        parse_bool_list(args.use_rsi_filter_values),
        parse_float_list(args.max_entry_distance_values),
        parse_float_list(args.tp1_values),
        parse_float_list(args.tp2_values),
        parse_float_list(args.stop_values),
        parse_float_list(args.tp1_close_pct_values),
        parse_bool_list(args.momentum_exit_values),
    ):
        if fast_ema >= slow_ema:
            continue
        if tp2_pips < tp1_pips:
            continue
        if stop_loss_pips <= 0:
            continue

        grid.append(
            Params(
                fast_ema=fast_ema,
                slow_ema=slow_ema,
                rsi_len=rsi_len,
                rsi_midline=rsi_midline,
                require_pullback_color=require_pullback_color,
                use_rsi_filter=use_rsi_filter,
                pip_size=args.pip_size,
                max_entry_distance_pips=max_entry_distance_pips,
                tp1_pips=tp1_pips,
                tp2_pips=tp2_pips,
                stop_loss_pips=stop_loss_pips,
                tp1_close_pct=tp1_close_pct,
                exit_runner_on_momentum_flip=exit_runner_on_momentum_flip,
                contracts_per_trade=args.contracts_per_trade,
                allow_longs=args.allow_longs,
                allow_shorts=args.allow_shorts,
            )
        )

    if not grid:
        raise ValueError("No valid parameter combinations after constraints.")
    return grid


def run_backtest(df: pd.DataFrame, p: Params) -> Result:
    close = df["close"]
    open_ = df["open"]
    high = df["high"]
    low = df["low"]

    fast_ema = close.ewm(span=p.fast_ema, adjust=False, min_periods=p.fast_ema).mean()
    slow_ema = close.ewm(span=p.slow_ema, adjust=False, min_periods=p.slow_ema).mean()
    rsi_vals = rsi(close, p.rsi_len)

    position = 0
    entry_price = 0.0
    remaining_qty = 0.0
    tp1_done = False

    gross_profit = 0.0
    gross_loss = 0.0
    wins = 0
    losses = 0
    trades = 0

    equity = 0.0
    equity_curve: List[float] = []
    trade_returns: List[float] = []
    current_trade_pnl = 0.0

    tp1_fraction = max(0.01, min(0.99, p.tp1_close_pct / 100.0))

    for i in range(1, len(df)):
        f = fast_ema.iat[i]
        s = slow_ema.iat[i]
        c = close.iat[i]
        o = open_.iat[i]
        h = high.iat[i]
        l = low.iat[i]
        r = rsi_vals.iat[i]

        if np.isnan(f) or np.isnan(s) or np.isnan(r):
            equity_curve.append(equity)
            continue

        trend_up = f > s
        trend_down = f < s
        between_ema = c <= max(f, s) and c >= min(f, s)
        pullback_red = c < o
        pullback_green = c > o

        long_momentum_ok = (not p.use_rsi_filter) or (r > p.rsi_midline)
        short_momentum_ok = (not p.use_rsi_filter) or (r < p.rsi_midline)

        entry_ref_long = min(f, s)
        entry_ref_short = max(f, s)
        dist_long_pips = abs(c - entry_ref_long) / p.pip_size
        dist_short_pips = abs(c - entry_ref_short) / p.pip_size

        long_distance_ok = dist_long_pips <= p.max_entry_distance_pips
        short_distance_ok = dist_short_pips <= p.max_entry_distance_pips

        long_pullback_ok = (not p.require_pullback_color) or pullback_red
        short_pullback_ok = (not p.require_pullback_color) or pullback_green

        long_signal = (
            p.allow_longs
            and trend_up
            and between_ema
            and long_pullback_ok
            and long_momentum_ok
            and long_distance_ok
        )
        short_signal = (
            p.allow_shorts
            and trend_down
            and between_ema
            and short_pullback_ok
            and short_momentum_ok
            and short_distance_ok
        )

        if position != 0:
            tp1_price = entry_price + (p.tp1_pips * p.pip_size * position)
            tp2_price = entry_price + (p.tp2_pips * p.pip_size * position)
            stop_price = entry_price - (p.stop_loss_pips * p.pip_size * position)

            stop_hit = (l <= stop_price) if position > 0 else (h >= stop_price)
            tp2_hit = (h >= tp2_price) if position > 0 else (l <= tp2_price)
            tp1_hit = (h >= tp1_price) if position > 0 else (l <= tp1_price)

            # Conservative tie-break: stop executes first when both touched in one bar.
            if stop_hit:
                pnl = (stop_price - entry_price) * position * remaining_qty
                current_trade_pnl += pnl
                if pnl >= 0:
                    gross_profit += pnl
                else:
                    gross_loss += pnl
                equity += pnl
                if current_trade_pnl >= 0:
                    wins += 1
                else:
                    losses += 1
                trade_returns.append(current_trade_pnl)
                trades += 1
                position = 0
                remaining_qty = 0.0
                tp1_done = False
                current_trade_pnl = 0.0

            elif tp2_hit:
                if not tp1_done:
                    qty_tp1 = remaining_qty * tp1_fraction
                    pnl1 = (tp1_price - entry_price) * position * qty_tp1
                    current_trade_pnl += pnl1
                    if pnl1 >= 0:
                        gross_profit += pnl1
                    else:
                        gross_loss += pnl1
                    equity += pnl1
                    remaining_qty -= qty_tp1
                    tp1_done = True

                pnl2 = (tp2_price - entry_price) * position * remaining_qty
                current_trade_pnl += pnl2
                if pnl2 >= 0:
                    gross_profit += pnl2
                else:
                    gross_loss += pnl2
                equity += pnl2

                if current_trade_pnl >= 0:
                    wins += 1
                else:
                    losses += 1
                trade_returns.append(current_trade_pnl)
                trades += 1
                position = 0
                remaining_qty = 0.0
                tp1_done = False
                current_trade_pnl = 0.0

            elif (not tp1_done) and tp1_hit:
                qty_tp1 = remaining_qty * tp1_fraction
                pnl1 = (tp1_price - entry_price) * position * qty_tp1
                current_trade_pnl += pnl1
                if pnl1 >= 0:
                    gross_profit += pnl1
                else:
                    gross_loss += pnl1
                equity += pnl1
                remaining_qty -= qty_tp1
                tp1_done = True

            if position != 0 and p.exit_runner_on_momentum_flip:
                if position > 0 and r < p.rsi_midline:
                    pnl = (c - entry_price) * position * remaining_qty
                    current_trade_pnl += pnl
                    if pnl >= 0:
                        gross_profit += pnl
                    else:
                        gross_loss += pnl
                    equity += pnl
                    if current_trade_pnl >= 0:
                        wins += 1
                    else:
                        losses += 1
                    trade_returns.append(current_trade_pnl)
                    trades += 1
                    position = 0
                    remaining_qty = 0.0
                    tp1_done = False
                    current_trade_pnl = 0.0
                elif position < 0 and r > p.rsi_midline:
                    pnl = (c - entry_price) * position * remaining_qty
                    current_trade_pnl += pnl
                    if pnl >= 0:
                        gross_profit += pnl
                    else:
                        gross_loss += pnl
                    equity += pnl
                    if current_trade_pnl >= 0:
                        wins += 1
                    else:
                        losses += 1
                    trade_returns.append(current_trade_pnl)
                    trades += 1
                    position = 0
                    remaining_qty = 0.0
                    tp1_done = False
                    current_trade_pnl = 0.0

        if position == 0:
            if long_signal:
                position = 1
                entry_price = c
                remaining_qty = float(p.contracts_per_trade)
                tp1_done = False
                current_trade_pnl = 0.0
            elif short_signal:
                position = -1
                entry_price = c
                remaining_qty = float(p.contracts_per_trade)
                tp1_done = False
                current_trade_pnl = 0.0

        equity_curve.append(equity)

    if position != 0 and remaining_qty > 0:
        c = close.iat[-1]
        pnl = (c - entry_price) * position * remaining_qty
        current_trade_pnl += pnl
        if pnl >= 0:
            gross_profit += pnl
        else:
            gross_loss += pnl
        equity += pnl
        if current_trade_pnl >= 0:
            wins += 1
        else:
            losses += 1
        trade_returns.append(current_trade_pnl)
        trades += 1
        equity_curve.append(equity)

    net = gross_profit + gross_loss
    wr = (wins / trades) if trades else 0.0
    eq_np = np.array(equity_curve, dtype=float)
    mdd = max_drawdown(eq_np)

    ret_np = np.array(trade_returns, dtype=float)
    if ret_np.size >= 2 and float(ret_np.std(ddof=1)) > 0:
        sharpe_like = float(ret_np.mean() / ret_np.std(ddof=1))
    else:
        sharpe_like = 0.0

    return Result(
        net_pnl=float(net),
        gross_profit=float(gross_profit),
        gross_loss=float(gross_loss),
        trades=trades,
        wins=wins,
        losses=losses,
        win_rate=float(wr),
        max_drawdown=float(mdd),
        sharpe_like=float(sharpe_like),
        params=p,
    )


def to_frame(results: Sequence[Result]) -> pd.DataFrame:
    rows = []
    for r in results:
        d = {
            "net_pnl": r.net_pnl,
            "gross_profit": r.gross_profit,
            "gross_loss": r.gross_loss,
            "trades": r.trades,
            "wins": r.wins,
            "losses": r.losses,
            "win_rate": r.win_rate,
            "max_drawdown": r.max_drawdown,
            "sharpe_like": r.sharpe_like,
        }
        for k, v in asdict(r.params).items():
            d[k] = v
        rows.append(d)
    return pd.DataFrame(rows)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Optimize BTC_tradingview_scalp_strategy params")
    p.add_argument(
        "--csv",
        default=None,
        help="Path to OHLC CSV (3m BTC recommended). If omitted, auto-detects a BTC CSV in the projects folder.",
    )
    p.add_argument("--out", default="btc_scalp_optimization_results.csv", help="Output CSV for all results.")
    p.add_argument("--top", type=int, default=15, help="How many top rows to print.")

    p.add_argument("--pip-size", type=float, default=1.0)
    p.add_argument("--contracts-per-trade", type=int, default=1)
    p.add_argument("--allow-longs", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--allow-shorts", action=argparse.BooleanOptionalAction, default=True)

    p.add_argument("--fast-ema-values", default="7,8,9,10,12")
    p.add_argument("--slow-ema-values", default="18,21,24,30")
    p.add_argument("--rsi-len-values", default="10,12,14")
    p.add_argument("--rsi-midline-values", default="48,50,52")
    p.add_argument("--require-pullback-color-values", default="true,false")
    p.add_argument("--use-rsi-filter-values", default="true,false")
    p.add_argument("--max-entry-distance-values", default="4,5,6,8")
    p.add_argument("--tp1-values", default="80,100,120,160,200")
    p.add_argument("--tp2-values", default="100,150,200,250,300")
    p.add_argument("--stop-values", default="80,100,150,200")
    p.add_argument("--tp1-close-pct-values", default="40,50,60")
    p.add_argument("--momentum-exit-values", default="true,false")

    return p.parse_args()


def resolve_csv_path(csv_arg: str | None) -> Path:
    if csv_arg:
        csv_path = Path(csv_arg).expanduser().resolve()
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        return csv_path

    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / "btc_3m.csv",
        script_dir / "BTC_3m.csv",
        script_dir / "btc.csv",
        script_dir / "BTC.csv",
    ]

    wildcard_hits = sorted(
        script_dir.glob("*btc*.csv"),
        key=lambda p: p.name.lower(),
    )
    candidates.extend(wildcard_hits)

    seen = set()
    ordered_candidates: List[Path] = []
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        ordered_candidates.append(c)

    for c in ordered_candidates:
        if c.exists():
            print(f"Auto-detected CSV: {c}")
            return c

    raise FileNotFoundError(
        "No CSV provided and no BTC CSV auto-detected in projects folder. "
        "Pass --csv with a file containing open/high/low/close columns."
    )


def main() -> None:
    args = parse_args()

    try:
        csv_path = resolve_csv_path(args.csv)
    except FileNotFoundError as exc:
        raise SystemExit(f"Error: {exc}") from None

    df = pd.read_csv(csv_path)
    df = normalize_columns(df)

    grid = build_grid(args)
    print(f"Evaluating {len(grid)} parameter combinations...")

    results: List[Result] = []
    for i, prm in enumerate(grid, start=1):
        if i % 100 == 0:
            print(f"  ...{i}/{len(grid)}")
        results.append(run_backtest(df, prm))

    results.sort(key=lambda x: (x.net_pnl, x.sharpe_like, x.win_rate), reverse=True)
    out_df = to_frame(results)
    out_df.to_csv(args.out, index=False)

    print("\nTop results:")
    preview_cols = [
        "net_pnl",
        "trades",
        "win_rate",
        "max_drawdown",
        "sharpe_like",
        "fast_ema",
        "slow_ema",
        "rsi_len",
        "rsi_midline",
        "max_entry_distance_pips",
        "tp1_pips",
        "tp2_pips",
        "stop_loss_pips",
        "tp1_close_pct",
        "exit_runner_on_momentum_flip",
        "use_rsi_filter",
        "require_pullback_color",
    ]
    print(out_df[preview_cols].head(args.top).to_string(index=False))

    best = results[0]
    print("\nBest parameter set (JSON):")
    print(json.dumps(asdict(best.params), indent=2))
    print(f"\nSaved full results to: {args.out}")


if __name__ == "__main__":
    main()

