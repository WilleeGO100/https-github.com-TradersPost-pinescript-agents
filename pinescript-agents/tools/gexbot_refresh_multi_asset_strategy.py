#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


def _fmt_num(value: float | None) -> str:
    if value is None:
        return "na"
    text = f"{value:.10f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".0"
    return text


def _parse_day_key(payload: dict[str, Any], path: Path) -> int:
    request_date = str(payload.get("request_date", "")).strip()
    if request_date:
        dt = datetime.strptime(request_date, "%Y-%m-%d")
        return dt.year * 10000 + dt.month * 100 + dt.day

    generated = str(payload.get("generated_at_utc", "")).replace("Z", "+00:00")
    if generated:
        dt = datetime.fromisoformat(generated)
        return dt.year * 10000 + dt.month * 100 + dt.day

    m = re.search(r"_(\d{8})", path.name)
    if m:
        return int(m.group(1))
    raise SystemExit(f"Cannot infer day key for file: {path}")


def _aggregate_top_levels(levels: list[dict[str, Any]]) -> tuple[list[float], list[float]]:
    agg: dict[float, float] = defaultdict(float)
    for row in levels:
        try:
            strike = float(row.get("strike"))
            gamma = float(row.get("gamma_signed"))
        except Exception:
            continue
        agg[strike] += gamma
    strikes = sorted(agg.keys())
    gamma_vals = [agg[s] for s in strikes]
    return strikes, gamma_vals


def _symbol_slug(symbol: str) -> str:
    return symbol.lower()


def _load_symbol_rows(hist_dir: Path, symbol: str) -> list[dict[str, Any]]:
    slug = _symbol_slug(symbol)
    files = sorted(hist_dir.glob(f"gexbot_{slug}_top_levels_*.json"))
    rows: dict[int, dict[str, Any]] = {}

    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if str(payload.get("symbol", "")).strip() != symbol:
            continue
        levels = payload.get("top_levels")
        if not isinstance(levels, list) or not levels:
            continue
        day_key = _parse_day_key(payload, path)
        strikes, gamma_vals = _aggregate_top_levels(levels)
        if not strikes:
            continue
        row = {
            "day_key": day_key,
            "spot": float(payload["spot"]) if payload.get("spot") is not None else None,
            "generated_at_utc": str(payload.get("generated_at_utc", "")),
            "source_url": str(payload.get("resolved_url", "")),
            "source_file": path.as_posix(),
            "strikes": strikes,
            "gamma": gamma_vals,
        }
        rows[day_key] = row

    return [rows[k] for k in sorted(rows.keys())]


def _series_csv(values: list[float]) -> str:
    return "|".join(_fmt_num(v) for v in values)


def _array_literal(values: list[float]) -> str:
    return ", ".join(_fmt_num(v) for v in values)


def _build_snapshot_block(symbol: str, suffix: str, row: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"// --- BEGIN AUTO-GENERATED GEX BLOCK ({symbol}) ---",
            f"// Source file: {row['source_file']}",
            f'// Symbol: "{symbol}"',
            f'// Generated at UTC: "{row["generated_at_utc"]}"',
            f'// Source URL: "{row["source_url"]}"',
            f"float gexSpot{suffix} = {_fmt_num(row['spot'])}",
            f'string gexGeneratedAt{suffix} = "{row["generated_at_utc"]}"',
            f'string gexSourceUrl{suffix} = "{row["source_url"]}"',
            f"var float[] gexStrikes{suffix} = array.from({_array_literal(row['strikes'])})",
            f"var float[] gexGamma{suffix} = array.from({_array_literal(row['gamma'])})",
            f"// --- END AUTO-GENERATED GEX BLOCK ({symbol}) ---",
        ]
    )


def _build_historical_block(symbol: str, suffix: str, rows: list[dict[str, Any]]) -> str:
    day_keys = ", ".join(str(r["day_key"]) for r in rows)
    strikes_csv = ", ".join(json.dumps(_series_csv(r["strikes"])) for r in rows)
    gamma_csv = ", ".join(json.dumps(_series_csv(r["gamma"])) for r in rows)
    return "\n".join(
        [
            f"// --- BEGIN AUTO-GENERATED HISTORICAL GEX DATASET ({symbol}) ---",
            "// day_key format: YYYYMMDD (exchange date)",
            f"// pipe-delimited rows must align by index with gexHistDayKeys{suffix}",
            f"var int[] gexHistDayKeys{suffix} = array.from({day_keys})",
            f"var string[] gexHistStrikesCsv{suffix} = array.from({strikes_csv})",
            f"var string[] gexHistGammaCsv{suffix} = array.from({gamma_csv})",
            f"// --- END AUTO-GENERATED HISTORICAL GEX DATASET ({symbol}) ---",
        ]
    )


def _replace_block(text: str, start_marker: str, end_marker: str, replacement: str) -> str:
    pattern = re.compile(
        re.escape(start_marker) + r".*?" + re.escape(end_marker), re.DOTALL
    )
    if not pattern.search(text):
        raise SystemExit(f"Could not find marker pair: {start_marker} ... {end_marker}")
    return pattern.sub(replacement, text, count=1)


def _update_symbol_blocks(
    *,
    text: str,
    symbol: str,
    suffix: str,
    rows: list[dict[str, Any]],
) -> str:
    if not rows:
        raise SystemExit(f"No rows found for symbol {symbol}.")

    latest = rows[-1]
    snapshot = _build_snapshot_block(symbol, suffix, latest)
    historical = _build_historical_block(symbol, suffix, rows)

    snap_start = f"// --- BEGIN AUTO-GENERATED GEX BLOCK ({symbol}) ---"
    snap_end = f"// --- END AUTO-GENERATED GEX BLOCK ({symbol}) ---"
    hist_start = f"// --- BEGIN AUTO-GENERATED HISTORICAL GEX DATASET ({symbol}) ---"
    hist_end = f"// --- END AUTO-GENERATED HISTORICAL GEX DATASET ({symbol}) ---"

    text = _replace_block(text, snap_start, snap_end, snapshot)
    text = _replace_block(text, hist_start, hist_end, historical)
    return text


def _has_symbol_markers(text: str, symbol: str) -> bool:
    snap_start = f"// --- BEGIN AUTO-GENERATED GEX BLOCK ({symbol}) ---"
    snap_end = f"// --- END AUTO-GENERATED GEX BLOCK ({symbol}) ---"
    hist_start = f"// --- BEGIN AUTO-GENERATED HISTORICAL GEX DATASET ({symbol}) ---"
    hist_end = f"// --- END AUTO-GENERATED HISTORICAL GEX DATASET ({symbol}) ---"
    return (
        snap_start in text
        and snap_end in text
        and hist_start in text
        and hist_end in text
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh NQ/ES auto-generated GEX blocks inside a multi-asset Pine strategy "
            "from historical gexbot_*_top_levels_*.json files."
        )
    )
    parser.add_argument(
        "--strategy",
        required=True,
        help="Path to strategy file containing NQ/ES auto-generated block markers.",
    )
    parser.add_argument(
        "--hist-dir",
        default="pinescript-agents/projects/analysis/gexbot_data/historical",
        help="Directory containing historical top-level JSON files.",
    )
    parser.add_argument(
        "--max-days",
        type=int,
        default=45,
        help="Maximum rows per symbol to emit into historical dataset arrays.",
    )
    parser.add_argument(
        "--symbols",
        default="NQ_NDX,ES_SPX",
        help="Comma-separated symbols to refresh when markers exist in target file.",
    )
    args = parser.parse_args()

    if args.max_days <= 0:
        raise SystemExit("--max-days must be > 0")

    strategy_path = Path(args.strategy)
    hist_dir = Path(args.hist_dir)
    if not strategy_path.exists():
        raise SystemExit(f"Strategy file not found: {strategy_path}")
    if not hist_dir.exists():
        raise SystemExit(f"Historical directory not found: {hist_dir}")

    text = strategy_path.read_text(encoding="utf-8")
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        raise SystemExit("No symbols specified.")

    updated: list[tuple[str, int]] = []
    for symbol in symbols:
        if symbol == "NQ_NDX":
            suffix = "Nq"
        elif symbol == "ES_SPX":
            suffix = "Es"
        else:
            raise SystemExit(f"Unsupported symbol: {symbol}. Supported: NQ_NDX, ES_SPX.")

        if not _has_symbol_markers(text, symbol):
            continue

        rows = _load_symbol_rows(hist_dir, symbol)
        if not rows:
            raise SystemExit(f"No {symbol} historical rows found.")
        rows = rows[-args.max_days :]
        text = _update_symbol_blocks(text=text, symbol=symbol, suffix=suffix, rows=rows)
        updated.append((symbol, len(rows)))

    if not updated:
        raise SystemExit(
            "No matching auto-generated marker blocks found for requested symbols in target strategy."
        )

    strategy_path.write_text(text, encoding="utf-8")

    print(f"Updated strategy: {strategy_path}")
    for symbol, count in updated:
        print(f"{symbol} rows emitted : {count}")
    print(f"Hist dir        : {hist_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
