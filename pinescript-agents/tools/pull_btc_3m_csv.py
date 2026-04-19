#!/usr/bin/env python3
"""
Pull BTC 3-minute candles and save an optimizer-ready CSV.

Default output columns include:
- time (UTC ISO8601)
- open, high, low, close, volume
"""

from __future__ import annotations

import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests


BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/{product}/candles"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch BTC 3m candles for optimizer input.")
    p.add_argument("--source", choices=["coinbase", "binance"], default="coinbase")
    p.add_argument("--symbol", default="BTCUSDT", help="Binance symbol (used when --source=binance)")
    p.add_argument("--product", default="BTC-USD", help="Coinbase product (used when --source=coinbase)")
    p.add_argument("--interval", default="3m", help="Binance interval (used when --source=binance)")
    p.add_argument("--bars", type=int, default=3000, help="Number of candles to fetch")
    p.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / "projects" / "btc_3m.csv"),
        help="Output CSV path",
    )
    return p.parse_args()


def fetch_klines(symbol: str, interval: str, bars: int) -> list[list]:
    if bars <= 0:
        raise ValueError("--bars must be > 0")

    all_rows: list[list] = []
    end_time_ms: int | None = None
    remaining = bars
    session = requests.Session()

    while remaining > 0:
        limit = min(1000, remaining)
        params: dict[str, int | str] = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if end_time_ms is not None:
            params["endTime"] = end_time_ms

        resp = session.get(BINANCE_KLINES_URL, params=params, timeout=20)
        resp.raise_for_status()
        batch = resp.json()

        if not isinstance(batch, list):
            raise RuntimeError(f"Unexpected Binance response type: {type(batch)}")
        if not batch:
            break

        all_rows.extend(batch)
        remaining -= len(batch)

        oldest_open_time = int(batch[0][0])
        end_time_ms = oldest_open_time - 1

        if len(batch) < limit:
            break

    return all_rows


def fetch_coinbase_candles(product: str, bars: int, granularity_sec: int = 60) -> pd.DataFrame:
    if bars <= 0:
        raise ValueError("--bars must be > 0")

    session = requests.Session()
    url = COINBASE_CANDLES_URL.format(product=product)
    max_per_call = 300
    remaining = bars
    end_dt = datetime.now(timezone.utc)
    parts: list[pd.DataFrame] = []

    while remaining > 0:
        need = min(max_per_call, remaining)
        start_dt = end_dt - timedelta(seconds=granularity_sec * need)
        params = {
            "granularity": granularity_sec,
            "start": start_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "end": end_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
        resp = session.get(url, params=params, timeout=20, headers={"User-Agent": "pinescript-agents/1.0"})
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data:
            break

        # Coinbase returns newest first: [time, low, high, open, close, volume]
        part = pd.DataFrame(data, columns=["unix", "low", "high", "open", "close", "volume"])
        parts.append(part)
        remaining -= len(part)

        oldest_unix = int(part["unix"].min())
        end_dt = datetime.fromtimestamp(oldest_unix - granularity_sec, tz=timezone.utc)

        if len(part) < need:
            break

    if not parts:
        raise RuntimeError("No candle data returned from Coinbase.")

    df = pd.concat(parts, ignore_index=True)
    df = df.drop_duplicates(subset=["unix"]).sort_values("unix")
    if len(df) > bars:
        df = df.tail(bars)
    return df.reset_index(drop=True)


def to_frame(rows: list[list], bars: int) -> pd.DataFrame:
    cols = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_asset_volume",
        "num_trades",
        "taker_buy_base",
        "taker_buy_quote",
        "ignore",
    ]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        raise RuntimeError("No candle data returned.")

    df = df.drop_duplicates(subset=["open_time"]).sort_values("open_time")
    if len(df) > bars:
        df = df.tail(bars)

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = df[["time", "open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
    return out


def main() -> None:
    args = parse_args()
    if args.source == "binance":
        rows = fetch_klines(symbol=args.symbol, interval=args.interval, bars=args.bars)
        out_df = to_frame(rows=rows, bars=args.bars)
    else:
        one_min_needed = args.bars * 3 + 50
        cb_df = fetch_coinbase_candles(product=args.product, bars=one_min_needed, granularity_sec=60)
        for c in ["open", "high", "low", "close", "volume"]:
            cb_df[c] = pd.to_numeric(cb_df[c], errors="coerce")
        cb_df["dt"] = pd.to_datetime(cb_df["unix"], unit="s", utc=True)
        cb_df = cb_df.sort_values("dt").set_index("dt")
        out_df = (
            cb_df[["open", "high", "low", "close", "volume"]]
            .resample("3min")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
            .tail(args.bars)
            .reset_index()
        )
        out_df["time"] = out_df["dt"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        out_df = out_df[["time", "open", "high", "low", "close", "volume"]]

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False)

    print(f"Saved {len(out_df)} rows to: {out_path}")
    print("Columns:", ", ".join(out_df.columns))


if __name__ == "__main__":
    main()
