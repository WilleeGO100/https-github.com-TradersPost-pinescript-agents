#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


TARGET_COLS = [
    "time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "net_gex",
    "gamma_flip",
    "call_wall",
    "put_wall",
    "inside_walls",
]


def _first_key(row: dict[str, Any], keys: list[str]) -> Any:
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("data", "rows", "bars", "candles", "result", "results"):
            v = payload.get(key)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


def _convert_timeseries(payload: Any) -> pd.DataFrame:
    rows = _extract_rows(payload)
    if not rows:
        return pd.DataFrame()

    out_rows: list[dict[str, Any]] = []
    for row in rows:
        ts = _first_key(row, ["time", "timestamp", "datetime", "date", "t"])
        o = _first_key(row, ["open", "o"])
        h = _first_key(row, ["high", "h"])
        l = _first_key(row, ["low", "l"])
        c = _first_key(row, ["close", "c", "last", "price"])
        v = _first_key(row, ["volume", "vol", "v"])
        g = _first_key(row, ["net_gex", "gex", "gamma", "net_gamma", "netGamma"])
        gf = _first_key(row, ["gamma_flip", "flip", "gex_flip", "gammaFlip"])
        cw = _first_key(row, ["call_wall", "callWall", "upper_wall"])
        pw = _first_key(row, ["put_wall", "putWall", "lower_wall"])
        iw = _first_key(row, ["inside_walls", "insideWalls"])

        out_rows.append(
            {
                "time": ts,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "net_gex": g,
                "gamma_flip": gf,
                "call_wall": cw,
                "put_wall": pw,
                "inside_walls": iw,
            }
        )

    df = pd.DataFrame(out_rows)

    # Numeric coercion
    for col in ["open", "high", "low", "close", "volume", "net_gex", "gamma_flip", "call_wall", "put_wall", "inside_walls"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Time coercion
    if "time" in df.columns:
        ts_num = pd.to_numeric(df["time"], errors="coerce")
        if ts_num.notna().any():
            # Heuristic: ms epoch if large
            unit = "ms" if ts_num.dropna().median() > 1e11 else "s"
            parsed = pd.to_datetime(ts_num, unit=unit, errors="coerce", utc=True)
            df["time"] = parsed.fillna(pd.to_datetime(df["time"], errors="coerce", utc=True))
        else:
            df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)

    # Derive inside_walls if missing and walls exist
    if "inside_walls" not in df.columns or df["inside_walls"].isna().all():
        if "call_wall" in df.columns and "put_wall" in df.columns and "close" in df.columns:
            df["inside_walls"] = (
                (df["close"] <= df["call_wall"]) & (df["close"] >= df["put_wall"])
            ).astype("float")

    # Fill volume default
    if "volume" in df.columns:
        df["volume"] = df["volume"].fillna(0)

    # Keep only rows with required OHLC/time
    req = ["time", "open", "high", "low", "close"]
    for c in req:
        if c not in df.columns:
            df[c] = pd.NA
    df = df.dropna(subset=req).sort_values("time").reset_index(drop=True)

    for c in TARGET_COLS:
        if c not in df.columns:
            df[c] = pd.NA
    return df[TARGET_COLS]


def _convert_ticker_catalog(payload: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for group in ("stocks", "indexes", "futures"):
        values = payload.get(group, [])
        if isinstance(values, list):
            for t in values:
                rows.append({"type": group[:-1] if group.endswith("s") else group, "ticker": str(t)})
    return pd.DataFrame(rows)


def main() -> None:
    p = argparse.ArgumentParser(description="Convert GEXBot JSON to CSV usable by local backtests.")
    p.add_argument("--input", required=True, help="Path to gexbot_data_*.json")
    p.add_argument("--out", default="", help="Output CSV path (optional)")
    args = p.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        raise SystemExit(f"Input file not found: {in_path}")

    payload = json.loads(in_path.read_text(encoding="utf-8"))

    out_path = Path(args.out) if args.out else in_path.with_suffix(".csv")

    # Mode 1: /tickers payload
    if isinstance(payload, dict) and any(k in payload for k in ("stocks", "indexes", "futures")):
        df = _convert_ticker_catalog(payload)
        df.to_csv(out_path, index=False)
        print("SUCCESS (ticker catalog)")
        print(f"Rows: {len(df)}")
        print(f"Saved: {out_path}")
        return

    # Mode 2: timeseries payload
    df = _convert_timeseries(payload)
    if df.empty:
        raise SystemExit(
            "No convertible OHLC/gamma rows found.\n"
            "Tip: /tickers returns only symbols. Pull a symbol-level timeseries endpoint, then run converter."
        )

    df.to_csv(out_path, index=False)
    print("SUCCESS (timeseries)")
    print(f"Rows: {len(df)}")
    print(f"Saved: {out_path}")
    print(f"Columns: {', '.join(df.columns)}")


if __name__ == "__main__":
    main()
