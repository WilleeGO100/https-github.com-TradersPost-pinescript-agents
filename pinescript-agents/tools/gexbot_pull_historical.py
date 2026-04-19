#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


DEFAULT_BASE_URL = "https://api.gexbot.com"
DEFAULT_AUTH_MODES = [
    "x-api-key",
    "authorization-bearer",
    "authorization-token",
    "pxD5m1JP9MDOM02dA_iS-2tzslYVRNDE5lPVGw3HYdc",
    "query-key",
    "query-token",
]
DEFAULT_DATE_PARAM_CANDIDATES = ["date", "trading_date", "as_of_date"]


def _parse_env_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("export "):
        text = text[len("export ") :].strip()
    if "=" not in text:
        return None
    key, value = text.split("=", 1)
    key = key.strip()
    if not key:
        return None
    value = value.strip()
    if (
        len(value) >= 2
        and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'"))
    ):
        value = value[1:-1]
    return key, value


def _load_env_file(path: Path) -> int:
    if not path.exists():
        return 0
    loaded = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(raw)
        if parsed is None:
            continue
        key, value = parsed
        # Respect already-exported environment values.
        if key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


def _load_env_variables() -> None:
    cwd = Path.cwd()
    here = Path(__file__).resolve()
    candidates = [
        cwd / ".env",
        cwd / ".env_gex",
        here.parents[2] / ".env",
        here.parents[2] / ".env_gex",
        here.parents[1] / ".env",
        here.parents[1] / ".env_gex",
    ]
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        _load_env_file(resolved)


@dataclass
class RequestResult:
    ok: bool
    status_code: int
    url: str
    payload: Any | None
    body_preview: str


def _auth_headers(api_key: str, mode: str) -> dict[str, str]:
    if mode == "x-api-key":
        return {"X-API-Key": api_key}
    if mode == "authorization-bearer":
        return {"Authorization": f"Bearer {api_key}"}
    if mode == "authorization-token":
        return {"Authorization": api_key}
    return {}


def _auth_params(api_key: str, mode: str) -> dict[str, str]:
    if mode == "query-api_key":
        return {"api_key": api_key}
    if mode == "query-key":
        return {"key": api_key}
    if mode == "query-token":
        return {"token": api_key}
    return {}


def _redact_url(url: str, secrets: list[str]) -> str:
    try:
        parts = urlsplit(url)
        q = parse_qsl(parts.query, keep_blank_values=True)
        redacted: list[tuple[str, str]] = []
        for k, v in q:
            if k.lower() in {"api_key", "key", "token"}:
                redacted.append((k, "REDACTED"))
            elif v in secrets and v:
                redacted.append((k, "REDACTED"))
            else:
                redacted.append((k, v))
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(redacted), parts.fragment)
        )
    except Exception:
        return url


def _is_number(v: Any) -> bool:
    try:
        float(v)
        return True
    except Exception:
        return False


def _extract_spot(payload: Any) -> float | None:
    if isinstance(payload, dict):
        for k in (
            "spot",
            "spot_price",
            "price",
            "underlying_price",
            "last",
            "current_price",
        ):
            if k in payload and _is_number(payload[k]):
                return float(payload[k])
        for v in payload.values():
            s = _extract_spot(v)
            if s is not None:
                return s
    elif isinstance(payload, list):
        for item in payload:
            s = _extract_spot(item)
            if s is not None:
                return s
    return None


def _extract_levels(payload: Any) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []

    def add_level(obj: dict[str, Any]) -> None:
        strike = None
        gamma = None
        level_type = ""

        for k in ("strike", "price", "level", "x"):
            if k in obj and _is_number(obj[k]):
                strike = float(obj[k])
                break
        for k in ("gex", "gamma", "value", "y", "net_gex", "abs_gex"):
            if k in obj and _is_number(obj[k]):
                gamma = float(obj[k])
                break
        for k in ("type", "side", "label", "kind"):
            if k in obj:
                level_type = str(obj[k])
                break

        if strike is not None and gamma is not None:
            levels.append(
                {
                    "strike": strike,
                    "gamma_signed": gamma,
                    "gamma_abs": abs(gamma),
                    "type": level_type or "unknown",
                }
            )

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            add_level(node)

            if node and all(_is_number(k) for k in node.keys()) and all(
                _is_number(v) for v in node.values()
            ):
                for k, v in node.items():
                    levels.append(
                        {
                            "strike": float(k),
                            "gamma_signed": float(v),
                            "gamma_abs": abs(float(v)),
                            "type": "map",
                        }
                    )

            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            if node and all(isinstance(item, (list, tuple)) for item in node):
                for row in node:
                    if len(row) >= 3 and _is_number(row[0]):
                        strike = float(row[0])
                        if _is_number(row[1]):
                            g = float(row[1])
                            levels.append(
                                {
                                    "strike": strike,
                                    "gamma_signed": g,
                                    "gamma_abs": abs(g),
                                    "type": "classic_vol",
                                }
                            )
                        if _is_number(row[2]):
                            g = float(row[2])
                            levels.append(
                                {
                                    "strike": strike,
                                    "gamma_signed": g,
                                    "gamma_abs": abs(g),
                                    "type": "classic_oi",
                                }
                            )
            for item in node:
                walk(item)

    walk(payload)

    best: dict[tuple[float, str], dict[str, Any]] = {}
    for lv in levels:
        key = (lv["strike"], lv["type"])
        prev = best.get(key)
        if prev is None or lv["gamma_abs"] > prev["gamma_abs"]:
            best[key] = lv
    return list(best.values())


def _rank_levels(
    levels: list[dict[str, Any]], spot: float | None, top_n: int
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for lv in levels:
        dist = abs(lv["strike"] - spot) if spot is not None else 0.0
        score = lv["gamma_abs"] / (1.0 + dist)
        ranked.append({**lv, "distance_to_spot": dist, "score": score})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:top_n]


def _daterange(start: date, end: date) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _call_endpoint(
    *,
    session: requests.Session,
    base_url: str,
    endpoint: str,
    api_key: str,
    auth_mode: str,
    date_param_name: str,
    target_day: date,
    timeout: int,
) -> RequestResult:
    url = base_url.rstrip("/") + endpoint
    params = {date_param_name: target_day.isoformat()}
    params.update(_auth_params(api_key, auth_mode))
    headers = {"Accept": "application/json"}
    headers.update(_auth_headers(api_key, auth_mode))

    resp = session.get(url, params=params, headers=headers, timeout=timeout)
    payload = None
    if "json" in resp.headers.get("content-type", "").lower():
        try:
            payload = resp.json()
        except Exception:
            payload = None
    return RequestResult(
        ok=(200 <= resp.status_code < 300),
        status_code=resp.status_code,
        url=resp.url,
        payload=payload,
        body_preview=resp.text[:500].replace("\n", " "),
    )


def _pull_symbol_history(
    *,
    session: requests.Session,
    base_url: str,
    api_key: str,
    ticker: str,
    symbol: str,
    aggregation_period: str,
    start_day: date,
    end_day: date,
    skip_weekends: bool,
    top_n: int,
    timeout: int,
    sleep_ms: int,
    out_dir: Path,
) -> tuple[int, int, Path]:
    endpoint = f"/{ticker}/classic/{aggregation_period}"
    secrets = [api_key]

    # Discover working auth/date-param combination once per ticker.
    discovery_log: list[dict[str, Any]] = []
    working_auth: str | None = None
    working_date_param: str | None = None
    probe_day = start_day
    for auth_mode in DEFAULT_AUTH_MODES:
        for date_param_name in DEFAULT_DATE_PARAM_CANDIDATES:
            try:
                rr = _call_endpoint(
                    session=session,
                    base_url=base_url,
                    endpoint=endpoint,
                    api_key=api_key,
                    auth_mode=auth_mode,
                    date_param_name=date_param_name,
                    target_day=probe_day,
                    timeout=timeout,
                )
            except Exception as e:
                discovery_log.append(
                    {
                        "auth_mode": auth_mode,
                        "date_param_name": date_param_name,
                        "error": str(e),
                    }
                )
                continue

            levels = _extract_levels(rr.payload) if rr.payload is not None else []
            discovery_log.append(
                {
                    "auth_mode": auth_mode,
                    "date_param_name": date_param_name,
                    "status_code": rr.status_code,
                    "ok": rr.ok,
                    "url": _redact_url(rr.url, secrets),
                    "body_preview": rr.body_preview,
                    "levels_found": len(levels),
                }
            )
            if rr.ok and rr.payload is not None and len(levels) > 0:
                working_auth = auth_mode
                working_date_param = date_param_name
                break
        if working_auth:
            break

    if working_auth is None or working_date_param is None:
        discovery_path = out_dir / f"gexbot_{symbol.lower()}_historical_probe_discovery.json"
        discovery_path.write_text(json.dumps(discovery_log, indent=2), encoding="utf-8")
        raise SystemExit(
            f"Failed to find a working auth/date-parameter combination for historical pulls ({ticker}).\n"
            f"Saved discovery log: {discovery_path}"
        )

    days = _daterange(start_day, end_day)
    summary: list[dict[str, Any]] = []
    ok_count = 0
    fail_count = 0

    for d in days:
        if skip_weekends and d.weekday() >= 5:
            summary.append({"date": d.isoformat(), "skipped": "weekend"})
            continue

        try:
            rr = _call_endpoint(
                session=session,
                base_url=base_url,
                endpoint=endpoint,
                api_key=api_key,
                auth_mode=working_auth,
                date_param_name=working_date_param,
                target_day=d,
                timeout=timeout,
            )
        except Exception as e:
            fail_count += 1
            summary.append({"date": d.isoformat(), "ok": False, "error": str(e)})
            continue

        if not rr.ok or rr.payload is None:
            fail_count += 1
            summary.append(
                {
                    "date": d.isoformat(),
                    "ok": False,
                    "status_code": rr.status_code,
                    "url": _redact_url(rr.url, secrets),
                    "body_preview": rr.body_preview,
                }
            )
            continue

        spot = _extract_spot(rr.payload)
        levels = _extract_levels(rr.payload)
        ranked = _rank_levels(levels, spot, top_n)

        day_stamp = d.strftime("%Y%m%d")
        raw_path = out_dir / f"gexbot_{symbol.lower()}_raw_{day_stamp}.json"
        top_json_path = out_dir / f"gexbot_{symbol.lower()}_top_levels_{day_stamp}.json"
        top_csv_path = out_dir / f"gexbot_{symbol.lower()}_top_levels_{day_stamp}.csv"

        raw_path.write_text(json.dumps(rr.payload, indent=2), encoding="utf-8")
        top_json_path.write_text(
            json.dumps(
                {
                    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "request_date": d.isoformat(),
                    "resolved_url": _redact_url(rr.url, secrets),
                    "auth_mode": working_auth,
                    "date_param_name": working_date_param,
                    "symbol": symbol,
                    "spot": spot,
                    "top_levels": ranked,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        with top_csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "strike",
                    "gamma_signed",
                    "gamma_abs",
                    "type",
                    "distance_to_spot",
                    "score",
                ],
            )
            w.writeheader()
            for row in ranked:
                w.writerow(row)

        ok_count += 1
        summary.append(
            {
                "date": d.isoformat(),
                "ok": True,
                "status_code": rr.status_code,
                "url": _redact_url(rr.url, secrets),
                "levels_found": len(levels),
                "raw_path": str(raw_path),
                "top_json_path": str(top_json_path),
                "top_csv_path": str(top_csv_path),
            }
        )
        if sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)

    summary_path = out_dir / (
        f"gexbot_{symbol.lower()}_historical_pull_summary_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    summary_path.write_text(
        json.dumps(
            {
                "symbol": symbol,
                "ticker": ticker,
                "aggregation_period": aggregation_period,
                "start_date": start_day.isoformat(),
                "end_date": end_day.isoformat(),
                "auth_mode": working_auth,
                "date_param_name": working_date_param,
                "ok_count": ok_count,
                "fail_count": fail_count,
                "results": summary,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("DONE")
    print(f"Ticker          : {ticker}")
    print(f"Symbol          : {symbol}")
    print(f"Endpoint        : {endpoint}")
    print(f"Auth mode       : {working_auth}")
    print(f"Date param      : {working_date_param}")
    print(f"Range           : {start_day} -> {end_day}")
    print(f"Successful days : {ok_count}")
    print(f"Failed days     : {fail_count}")
    print(f"Summary         : {summary_path}")
    return ok_count, fail_count, summary_path


def main() -> None:
    _load_env_variables()
    p = argparse.ArgumentParser(
        description="Pull historical GEXBot classic data across a date range and save daily files."
    )
    p.add_argument("--api-key", default=os.getenv("GEXBOT_API_KEY", ""))
    p.add_argument("--base-url", default=os.getenv("GEXBOT_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument("--ticker", default="NQ_NDX", help="Classic ticker, e.g. NQ_NDX or ES_SPX.")
    p.add_argument(
        "--tickers",
        default="",
        help="Comma-separated tickers (e.g. NQ_NDX,ES_SPX). Overrides --ticker.",
    )
    p.add_argument("--aggregation-period", default="zero", help="Classic aggregation period.")
    p.add_argument("--symbol", default="", help="Symbol label for saved metadata (defaults to ticker).")
    p.add_argument("--start-date", required=True, help="Start date YYYY-MM-DD.")
    p.add_argument("--end-date", default="", help="End date YYYY-MM-DD (default: start-date).")
    p.add_argument("--skip-weekends", action="store_true", help="Skip Saturdays/Sundays.")
    p.add_argument("--top-n", type=int, default=12)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--sleep-ms", type=int, default=200, help="Pause between requests.")
    p.add_argument(
        "--out-dir",
        default="projects/analysis/gexbot_data/historical",
        help="Directory where daily files are saved.",
    )
    args = p.parse_args()

    if not args.api_key:
        raise SystemExit("Missing API key. Pass --api-key or set GEXBOT_API_KEY.")
    if not args.base_url.startswith("http"):
        raise SystemExit(f"Invalid base URL: {args.base_url}")

    start_day = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_day = (
        datetime.strptime(args.end_date, "%Y-%m-%d").date()
        if args.end_date
        else start_day
    )
    if end_day < start_day:
        raise SystemExit("end-date must be >= start-date")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    if args.tickers.strip():
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    elif args.ticker.strip().lower() == "both":
        tickers = ["NQ_NDX", "ES_SPX"]
    else:
        tickers = [args.ticker.strip()]
    if not tickers:
        raise SystemExit("No valid ticker(s) provided.")
    if len(tickers) > 1 and args.symbol:
        raise SystemExit("--symbol can only be used when pulling a single ticker.")

    total_ok = 0
    total_fail = 0
    for ticker in tickers:
        symbol = args.symbol if args.symbol else ticker
        ok_count, fail_count, _ = _pull_symbol_history(
            session=session,
            base_url=args.base_url,
            api_key=args.api_key,
            ticker=ticker,
            symbol=symbol,
            aggregation_period=args.aggregation_period,
            start_day=start_day,
            end_day=end_day,
            skip_weekends=args.skip_weekends,
            top_n=args.top_n,
            timeout=args.timeout,
            sleep_ms=args.sleep_ms,
            out_dir=out_dir,
        )
        total_ok += ok_count
        total_fail += fail_count

    if len(tickers) > 1:
        print("DONE (ALL TICKERS)")
        print(f"Tickers         : {', '.join(tickers)}")
        print(f"Total successes : {total_ok}")
        print(f"Total failures  : {total_fail}")


if __name__ == "__main__":
    main()
