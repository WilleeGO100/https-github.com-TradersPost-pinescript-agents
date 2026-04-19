#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _to_float(value: Any, field: str) -> float:
    try:
        return float(value)
    except Exception as exc:
        raise SystemExit(f"Invalid numeric value for '{field}': {value}") from exc


def _fmt_num(value: float) -> str:
    text = f"{value:.10f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".0"
    return text


def _fmt_float_literal(value: Any) -> str:
    if value is None:
        return "na"
    try:
        number = float(value)
    except Exception:
        return "na"
    if not math.isfinite(number):
        return "na"
    return _fmt_num(number)


def _fmt_string_literal(value: Any) -> str:
    return json.dumps("" if value is None else str(value))


def _parse_day_key_from_iso(iso_text: str) -> int:
    try:
        dt = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
    except Exception as exc:
        raise SystemExit(f"Invalid ISO datetime value: {iso_text}") from exc
    return dt.year * 10000 + dt.month * 100 + dt.day


def _parse_day_key_from_ymd(date_text: str) -> int:
    try:
        d = datetime.strptime(date_text, "%Y-%m-%d")
    except Exception as exc:
        raise SystemExit(f"Invalid YYYY-MM-DD date value: {date_text}") from exc
    return d.year * 10000 + d.month * 100 + d.day


def _parse_day_key_from_timestamp(timestamp_value: Any) -> int:
    try:
        dt = datetime.fromtimestamp(float(timestamp_value), tz=timezone.utc)
    except Exception as exc:
        raise SystemExit(f"Invalid UNIX timestamp value: {timestamp_value}") from exc
    return dt.year * 10000 + dt.month * 100 + dt.day


def _parse_day_key_from_path(path: Path) -> int:
    match = re.search(r"(\d{8})", path.stem)
    if not match:
        raise SystemExit(
            f"Could not derive day key from file name '{path.name}'. "
            "Expected an embedded YYYYMMDD date."
        )
    return int(match.group(1))


def _day_key_to_date(day_key: int) -> date:
    year = day_key // 10000
    month = (day_key % 10000) // 100
    day = day_key % 100
    return date(year, month, day)


def _date_to_day_key(value: date) -> int:
    return value.year * 10000 + value.month * 100 + value.day


def _next_day_key(day_key: int, skip_weekends: bool) -> int:
    d = _day_key_to_date(day_key)
    while True:
        d += timedelta(days=1)
        if not skip_weekends or d.weekday() < 5:
            return _date_to_day_key(d)


def _derive_walls_from_levels(levels: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    agg: dict[float, float] = defaultdict(float)
    for idx, row in enumerate(levels):
        if not isinstance(row, dict):
            raise SystemExit(f"Invalid top_levels row at index {idx}: expected object")
        strike = _to_float(row.get("strike"), "strike")
        gamma = _to_float(row.get("gamma_signed"), "gamma_signed")
        agg[strike] += gamma

    positive = [(strike, gamma) for strike, gamma in agg.items() if gamma > 0]
    negative = [(strike, gamma) for strike, gamma in agg.items() if gamma < 0]

    call_wall = max(positive, key=lambda kv: kv[1])[0] if positive else None
    put_wall = min(negative, key=lambda kv: kv[1])[0] if negative else None
    return call_wall, put_wall


def _derive_walls_from_csv_rows(rows: list[dict[str, str]]) -> tuple[float | None, float | None]:
    agg: dict[float, float] = defaultdict(float)
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SystemExit(f"Invalid CSV row at index {idx}: expected object")
        strike = _to_float(row.get("strike"), "strike")
        gamma = _to_float(row.get("gamma_signed"), "gamma_signed")
        agg[strike] += gamma

    positive = [(strike, gamma) for strike, gamma in agg.items() if gamma > 0]
    negative = [(strike, gamma) for strike, gamma in agg.items() if gamma < 0]

    call_wall = max(positive, key=lambda kv: kv[1])[0] if positive else None
    put_wall = min(negative, key=lambda kv: kv[1])[0] if negative else None
    return call_wall, put_wall


def _first_present(payload: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _raw_companion_path(top_levels_path: Path) -> Path:
    name = top_levels_path.name.replace("_top_levels_", "_raw_")
    return top_levels_path.with_name(name)


def _json_companion_path(csv_path: Path) -> Path:
    return csv_path.with_suffix(".json")


def _extract_row_from_csv(csv_path: Path) -> tuple[int, str, Any, Any, Any, Any]:
    top_payload = _load_json(_json_companion_path(csv_path))
    raw_path = csv_path.with_name(csv_path.name.replace("_top_levels_", "_raw_").replace(".csv", ".json"))
    raw_payload = _load_json(raw_path) if raw_path.exists() else None
    symbol = None
    day_key = _parse_day_key_from_path(csv_path)
    if top_payload is not None:
        symbol = _first_present(top_payload, ["symbol", "ticker"])
        day_key_value = _first_present(top_payload, ["request_date"])
        if isinstance(day_key_value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_key_value):
            day_key = _parse_day_key_from_ymd(day_key_value)
        elif day_key_value is not None:
            day_key = _parse_day_key_from_iso(str(day_key_value))

    try:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception as exc:
        raise SystemExit(f"Unable to read CSV {csv_path.name}: {exc}") from exc

    if not rows:
        raise SystemExit(f"CSV file is empty: {csv_path.name}")

    if symbol is None and top_payload is not None:
        symbol = _first_present(top_payload, ["symbol", "ticker"])
    if symbol is None:
        match = re.search(r"gexbot_(.+?)_top_levels_", csv_path.name)
        symbol = match.group(1).upper() if match else "NQ_NDX"

    source_payload = raw_payload or top_payload or {}
    spot = _first_present(source_payload, ["spot"])
    zero_gamma = _first_present(source_payload, ["zero_gamma", "zeroGamma"])
    call_wall = _first_present(source_payload, ["call_wall", "callWall", "major_pos_vol", "major_pos_oi"])
    put_wall = _first_present(source_payload, ["put_wall", "putWall", "major_neg_vol", "major_neg_oi"])

    if call_wall is None or put_wall is None:
        derived_call, derived_put = _derive_walls_from_csv_rows(rows)
        if call_wall is None:
            call_wall = derived_call
        if put_wall is None:
            put_wall = derived_put

    return (
        day_key,
        str(symbol),
        spot,
        zero_gamma,
        call_wall,
        put_wall,
    )


def _extract_row(
    payload: dict[str, Any],
    source_path: Path,
    *,
    day_key_override: int | None = None,
) -> tuple[int, str, Any, Any, Any, Any]:
    symbol = _first_present(payload, ["symbol", "ticker"])
    if symbol is None:
        raise SystemExit(f"Missing symbol/ticker field in {source_path.name}")

    if day_key_override is not None:
        day_key = day_key_override
    else:
        day_key_value = _first_present(payload, ["request_date", "generated_at_utc", "timestamp"])
        if isinstance(day_key_value, str):
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_key_value):
                day_key = _parse_day_key_from_ymd(day_key_value)
            else:
                day_key = _parse_day_key_from_iso(day_key_value)
        elif day_key_value is not None:
            day_key = _parse_day_key_from_timestamp(day_key_value)
        else:
            day_key = _parse_day_key_from_path(source_path)

    spot = _first_present(payload, ["spot"])
    zero_gamma = _first_present(payload, ["zero_gamma", "zeroGamma"])
    call_wall = _first_present(payload, ["call_wall", "callWall", "major_pos_vol", "major_pos_oi"])
    put_wall = _first_present(payload, ["put_wall", "putWall", "major_neg_vol", "major_neg_oi"])

    levels = payload.get("top_levels")
    if isinstance(levels, list) and levels:
        derived_call, derived_put = _derive_walls_from_levels(levels)
        if call_wall is None:
            call_wall = derived_call
        if put_wall is None:
            put_wall = derived_put

    return (
        day_key,
        str(symbol),
        spot,
        zero_gamma,
        call_wall,
        put_wall,
    )


def _extract_row_from_top_levels(top_levels_path: Path) -> tuple[int, str, Any, Any, Any, Any]:
    raw_path = _raw_companion_path(top_levels_path)
    raw_payload = _load_json(raw_path) if raw_path.exists() else None
    top_payload = _load_json(top_levels_path)
    if top_payload is not None:
        day_key_value = _first_present(top_payload, ["request_date"])
        day_key_override = None
        if isinstance(day_key_value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_key_value):
            day_key_override = _parse_day_key_from_ymd(day_key_value)
        elif day_key_value is not None:
            day_key_override = _parse_day_key_from_iso(str(day_key_value))

        if raw_payload is not None:
            row = _extract_row(raw_payload, raw_path, day_key_override=day_key_override)
            return row
        return _extract_row(top_payload, top_levels_path, day_key_override=day_key_override)

    if raw_payload is not None:
        return _extract_row(raw_payload, raw_path)
    raise SystemExit(f"Unable to load JSON from {top_levels_path.name}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a Pine historical GEX dataset block using a compact GexRow schema."
    )
    parser.add_argument(
        "--dir",
        default="projects/analysis/gexbot_data",
        help="Directory containing GEX JSON files.",
    )
    parser.add_argument(
        "--pattern",
        default="gexbot_nq_ndx_top_levels_*.csv",
        help="Filename pattern to scan in --dir.",
    )
    parser.add_argument(
        "--require-symbol",
        default="NQ_NDX",
        help="Only include files whose payload symbol matches this value.",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Optional output file path for the generated .pine.inc block.",
    )
    parser.add_argument(
        "--include-current",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Add/overwrite today's YYYYMMDD row using the latest available levels.",
    )
    parser.add_argument(
        "--forward-days",
        type=int,
        default=0,
        help="Project latest/current levels forward by N additional days.",
    )
    parser.add_argument(
        "--skip-weekends",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="When projecting forward, skip Saturday/Sunday day keys.",
    )
    args = parser.parse_args()

    script_repo_root = Path(__file__).resolve().parents[1]
    input_dir = Path(args.dir)
    if input_dir.is_absolute():
        candidate_roots = [input_dir]
    else:
        candidate_roots = [
            (Path.cwd() / input_dir).resolve(),
            (script_repo_root / input_dir).resolve(),
        ]

    existing_roots: list[Path] = []
    for root in candidate_roots:
        if root.exists() and root not in existing_roots:
            existing_roots.append(root)

    if not existing_roots:
        checked = ", ".join(str(p) for p in candidate_roots)
        raise SystemExit(f"Directory not found. Checked: {checked}")

    files: list[Path] = []
    chosen_root = existing_roots[0]
    for root in existing_roots:
        matches = sorted(root.rglob(args.pattern))
        if matches:
            files = matches
            chosen_root = root
            break

    if not files:
        checked = ", ".join(str(p) for p in existing_roots)
        raise SystemExit(
            f"No files matching '{args.pattern}' found (recursive search). "
            f"Checked roots: {checked}"
        )

    by_day: dict[int, tuple[str, str, str, str, str]] = {}
    used_files = 0
    skipped_symbol = 0
    skipped_payload = 0

    for path in files:
        if path.suffix.lower() == ".csv":
            day_key, row_symbol, spot, zero_gamma, call_wall, put_wall = _extract_row_from_csv(path)
        else:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                skipped_payload += 1
                continue

            symbol = str(payload.get("symbol", ""))
            if symbol != args.require_symbol:
                skipped_symbol += 1
                continue

            day_key, row_symbol, spot, zero_gamma, call_wall, put_wall = _extract_row_from_top_levels(path)

        if str(row_symbol) != args.require_symbol:
            skipped_symbol += 1
            continue

        by_day[day_key] = (
            row_symbol,
            _fmt_float_literal(spot),
            _fmt_float_literal(zero_gamma),
            _fmt_float_literal(call_wall),
            _fmt_float_literal(put_wall),
        )
        used_files += 1

    if not by_day:
        raise SystemExit(
            "No valid historical rows produced. Check --require-symbol and input files."
        )

    if args.forward_days < 0:
        raise SystemExit("--forward-days must be >= 0")

    projected_current = 0
    projected_future = 0

    latest_day_key = max(by_day.keys())
    latest_row = by_day[latest_day_key]

    base_day_key = latest_day_key
    if args.include_current:
        today_utc = datetime.now(timezone.utc).date()
        today_key = _date_to_day_key(today_utc)
        by_day[today_key] = latest_row
        base_day_key = today_key
        projected_current = 1

    next_key = base_day_key
    for _ in range(args.forward_days):
        next_key = _next_day_key(next_key, skip_weekends=args.skip_weekends)
        by_day[next_key] = by_day[base_day_key]
        projected_future += 1

    day_keys = sorted(by_day.keys())
    row_literals = []
    for day_key in day_keys:
        symbol_literal, spot_literal, zero_gamma_literal, call_wall_literal, put_wall_literal = by_day[day_key]
        row_literals.append(
            "    GexRow.new("
            f"{day_key}, {_fmt_string_literal(symbol_literal)}, "
            f"{spot_literal}, {zero_gamma_literal}, {call_wall_literal}, {put_wall_literal}"
            ")"
        )

    block = (
        f"// --- BEGIN AUTO-GENERATED HISTORICAL GEX DATASET ({args.require_symbol}) ---\n"
        "// day_key format: YYYYMMDD (exchange date)\n"
        "type GexRow\n"
        "    int dayKey\n"
        "    string symbol\n"
        "    float spot\n"
        "    float zeroGamma\n"
        "    float callWall\n"
        "    float putWall\n"
        "var GexRow[] gexHistRows = array.from(\n"
        + ",\n".join(row_literals)
        + "\n)\n"
        f"// --- END AUTO-GENERATED HISTORICAL GEX DATASET ({args.require_symbol}) ---\n"
    )

    print(block, end="")
    print(f"Symbol required : {args.require_symbol}")
    print(f"Source root     : {chosen_root}")
    print(f"Files scanned   : {len(files)}")
    print(f"Files used      : {used_files}")
    print(f"Skipped symbol  : {skipped_symbol}")
    print(f"Skipped payload : {skipped_payload}")
    print(f"Current row add : {projected_current}")
    print(f"Forward days add: {projected_future}")
    print(f"Days emitted    : {len(day_keys)}")
    print(f"Date range      : {day_keys[0]} -> {day_keys[-1]}")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(block, encoding="utf-8")
        print(f"Saved include   : {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
