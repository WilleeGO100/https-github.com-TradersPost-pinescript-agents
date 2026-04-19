#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _to_float(value: Any, field: str) -> float:
    try:
        return float(value)
    except Exception as exc:
        raise SystemExit(f"Invalid numeric value for '{field}': {value}") from exc


def _parse_date(yyyy_mm_dd: str) -> date:
    try:
        return datetime.strptime(yyyy_mm_dd, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit(f"Invalid date '{yyyy_mm_dd}'. Expected YYYY-MM-DD.") from exc


def _parse_day_key_from_iso(iso_text: str) -> int:
    try:
        dt = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
    except Exception as exc:
        raise SystemExit(f"Invalid ISO datetime value: {iso_text}") from exc
    return dt.year * 10000 + dt.month * 100 + dt.day


def _day_key_from_date(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def _date_from_day_key(day_key: int) -> date:
    year = day_key // 10000
    month = (day_key // 100) % 100
    day = day_key % 100
    return date(year, month, day)


def _load_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Input file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Top-level JSON must be an object: {path}")
    return payload


def _aggregate_levels(levels: list[dict[str, Any]]) -> dict[float, float]:
    aggregated: dict[float, float] = defaultdict(float)
    for idx, row in enumerate(levels):
        if not isinstance(row, dict):
            raise SystemExit(f"Invalid top_levels row at index {idx}: expected object")
        strike = _to_float(row.get("strike"), "strike")
        gamma = _to_float(row.get("gamma_signed"), "gamma_signed")
        aggregated[strike] += gamma
    return aggregated


def _fmt_num(value: float | None) -> str:
    if value is None:
        return "na"
    text = f"{value:.10f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".0"
    return text


def _extract_row(path: Path, require_symbol: str) -> dict[str, Any]:
    payload = _load_payload(path)
    symbol = str(payload.get("symbol", ""))
    if symbol != require_symbol:
        raise SystemExit(
            f"Symbol mismatch: expected '{require_symbol}' but got '{symbol}' in {path}"
        )

    levels = payload.get("top_levels")
    if not isinstance(levels, list) or not levels:
        raise SystemExit(f"Missing or empty 'top_levels' in: {path}")

    aggregated = _aggregate_levels(levels)
    if not aggregated:
        raise SystemExit(f"No valid strike/gamma rows found in: {path}")

    generated_at = str(payload.get("generated_at_utc", ""))
    request_date = str(payload.get("request_date", ""))
    if request_date:
        day_key = _day_key_from_date(_parse_date(request_date))
    elif generated_at:
        day_key = _parse_day_key_from_iso(generated_at)
    else:
        day_key = _day_key_from_date(datetime.now(timezone.utc).date())

    spot = (
        _to_float(payload.get("spot"), "spot")
        if payload.get("spot") is not None
        else None
    )
    zero_gamma = (
        _to_float(payload.get("zero_gamma"), "zero_gamma")
        if payload.get("zero_gamma") is not None
        else None
    )

    positive = [(strike, gamma) for strike, gamma in aggregated.items() if gamma > 0]
    negative = [(strike, gamma) for strike, gamma in aggregated.items() if gamma < 0]
    call_wall = max(positive, key=lambda kv: kv[1])[0] if positive else None
    put_wall = min(negative, key=lambda kv: kv[1])[0] if negative else None

    return {
        "day_key": day_key,
        "symbol": symbol,
        "spot": spot,
        "zero_gamma": zero_gamma,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "generated_at_utc": generated_at,
        "source_url": str(payload.get("resolved_url", "")),
        "source_file": path.as_posix(),
    }


def _find_input_files(search_dir: Path, require_symbol: str) -> list[Path]:
    symbol_slug = require_symbol.lower()
    files = sorted(search_dir.glob(f"gexbot_{symbol_slug}_top_levels_*.json"))
    if files:
        return files

    fallback = sorted(search_dir.glob("gexbot_*_top_levels_*.json"))
    filtered = [p for p in fallback if symbol_slug in p.name.lower()]
    if filtered:
        return filtered

    raise SystemExit(
        f"No matching top-level JSON files found for symbol '{require_symbol}' in: {search_dir}"
    )


def _build_pine_block(
    *,
    title: str,
    symbol: str,
    generated_at: str,
    source_note: str,
    rows: list[dict[str, Any]],
    type_name: str,
    array_name: str,
) -> str:
    escaped_generated = generated_at.replace('"', '\\"')
    escaped_source_note = source_note.replace('"', '\\"')

    row_text = ",\n    ".join(
        [
            (
                f"{type_name}.new({row['day_key']}, {json.dumps(symbol)}, "
                f"{_fmt_num(row['spot'])}, {_fmt_num(row['zero_gamma'])}, "
                f"{_fmt_num(row['call_wall'])}, {_fmt_num(row['put_wall'])})"
            )
            for row in rows
        ]
    )
    if not row_text:
        row_text = f"{type_name}.new(0, {json.dumps(symbol)}, na, na, na, na)"

    lines = [
        f"// --- BEGIN AUTO-GENERATED GEX BLOCK ({title}) ---",
        f'// Symbol: "{symbol}"',
        f'// Generated at UTC: "{generated_at}"',
        f'// Source note: "{source_note}"',
        f"type {type_name}",
        "    int dayKey",
        "    string symbol",
        "    float spot",
        "    float zeroGamma",
        "    float callWall",
        "    float putWall",
        f'string {array_name}GeneratedAt = "{escaped_generated}"',
        f'string {array_name}Source = "{escaped_source_note}"',
        f"var {type_name}[] {array_name} = array.from(",
        f"    {row_text}",
        ")",
        f"// --- END AUTO-GENERATED GEX BLOCK ({title}) ---",
    ]
    return "\n".join(lines) + "\n"


def _build_forward_rows(
    *,
    history_rows: list[dict[str, Any]],
    start_day: date,
    future_days: int,
    skip_weekends: bool,
    symbol: str,
) -> list[dict[str, Any]]:
    if not history_rows:
        raise SystemExit("Cannot create forward rows: no history rows available.")

    start_key = _day_key_from_date(start_day)
    prior_rows = [r for r in history_rows if r["day_key"] <= start_key]
    source_row = prior_rows[-1] if prior_rows else history_rows[-1]

    out: list[dict[str, Any]] = []
    end_day = start_day + timedelta(days=future_days)
    cur = start_day
    while cur <= end_day:
        if skip_weekends and cur.weekday() >= 5:
            cur += timedelta(days=1)
            continue
        out.append(
            {
                "day_key": _day_key_from_date(cur),
                "symbol": symbol,
                "spot": source_row["spot"],
                "zero_gamma": source_row["zero_gamma"],
                "call_wall": source_row["call_wall"],
                "put_wall": source_row["put_wall"],
            }
        )
        cur += timedelta(days=1)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert GEXBot top-level JSON files into Pine blocks for historical and "
            "forward (carried) day-level rows."
        )
    )
    parser.add_argument(
        "--input",
        default="",
        help="Optional single gexbot_*_top_levels_*.json file. If empty, reads all matching files in --dir.",
    )
    parser.add_argument(
        "--dir",
        default="projects/analysis/gexbot_data/historical",
        help="Directory used when --input is not supplied.",
    )
    parser.add_argument(
        "--require-symbol",
        default="NQ_NDX",
        help="Expected symbol (e.g. NQ_NDX or ES_SPX).",
    )
    parser.add_argument(
        "--history-out",
        default="",
        help="Output path for historical Pine include.",
    )
    parser.add_argument(
        "--forward-out",
        default="",
        help="Output path for forward Pine include.",
    )
    parser.add_argument(
        "--future-days",
        type=int,
        default=30,
        help="How many calendar days ahead to carry forward from start date.",
    )
    parser.add_argument(
        "--forward-start-date",
        default="",
        help="Forward file start date YYYY-MM-DD (default: previous UTC day).",
    )
    parser.add_argument(
        "--skip-weekends-forward",
        action="store_true",
        help="Skip Saturday/Sunday rows in forward output.",
    )
    args = parser.parse_args()

    if args.future_days < 0:
        raise SystemExit("--future-days must be >= 0")

    if args.input:
        files = [Path(args.input)]
    else:
        files = _find_input_files(Path(args.dir), args.require_symbol)

    by_day: dict[int, dict[str, Any]] = {}
    for path in files:
        row = _extract_row(path, args.require_symbol)
        prior = by_day.get(row["day_key"])
        if prior is None or row["source_file"] > prior["source_file"]:
            by_day[row["day_key"]] = row

    history_rows = [by_day[k] for k in sorted(by_day.keys())]
    if not history_rows:
        raise SystemExit("No valid history rows were generated.")

    now_utc = datetime.now(timezone.utc)
    generated_at = now_utc.isoformat()
    symbol = args.require_symbol

    history_source = (
        files[0].as_posix()
        if len(files) == 1
        else f"{len(files)} files from {Path(args.dir).as_posix()}"
    )
    history_block = _build_pine_block(
        title=f"{symbol} HISTORY",
        symbol=symbol,
        generated_at=generated_at,
        source_note=history_source,
        rows=history_rows,
        type_name="GexHistRow",
        array_name="gexHistRows",
    )

    if args.forward_start_date:
        forward_start = _parse_date(args.forward_start_date)
    else:
        forward_start = (now_utc - timedelta(days=1)).date()

    forward_rows = _build_forward_rows(
        history_rows=history_rows,
        start_day=forward_start,
        future_days=args.future_days,
        skip_weekends=args.skip_weekends_forward,
        symbol=symbol,
    )
    source_day_key = history_rows[-1]["day_key"]
    source_day = _date_from_day_key(source_day_key).isoformat()
    forward_block = _build_pine_block(
        title=f"{symbol} FORWARD_CARRY",
        symbol=symbol,
        generated_at=generated_at,
        source_note=f"carry-forward from source day {source_day}",
        rows=forward_rows,
        type_name="GexFwdRow",
        array_name="gexFwdRows",
    )

    print(history_block, end="")
    print(forward_block, end="")

    if args.history_out:
        history_out = Path(args.history_out)
        history_out.parent.mkdir(parents=True, exist_ok=True)
        history_out.write_text(history_block, encoding="utf-8")
        print(f"Saved history include: {history_out}")

    if args.forward_out:
        forward_out = Path(args.forward_out)
        forward_out.parent.mkdir(parents=True, exist_ok=True)
        forward_out.write_text(forward_block, encoding="utf-8")
        print(f"Saved forward include: {forward_out}")

    print(f"Symbol               : {symbol}")
    print(f"Input files          : {len(files)}")
    print(f"History rows         : {len(history_rows)}")
    print(f"Forward start        : {forward_start.isoformat()}")
    print(f"Forward days         : {args.future_days}")
    print(f"Forward rows         : {len(forward_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
