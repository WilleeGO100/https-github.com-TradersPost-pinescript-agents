#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


DEFAULT_BASE_URL = "https://api.gexbot.com"
DEFAULT_ENDPOINTS = [
    "/gex",
    "/v1/gex",
    "/api/gex",
    "/gamma",
    "/v1/gamma",
    "/api/gamma",
    "/levels",
    "/v1/levels",
    "/api/levels",
    "/futures/gex",
    "/v1/futures/gex",
]
DEFAULT_SYMBOL_ALIASES = ["ES_SPX", "ES", "MES", "SPX", "NQ_NDX"]


@dataclass
class FetchResult:
    url: str
    status_code: int
    auth_mode: str
    endpoint: str
    symbol: str
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
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(redacted), parts.fragment))
    except Exception:
        return url


def _try_fetch(
    session: requests.Session,
    base_url: str,
    endpoint: str,
    symbol: str,
    api_key: str,
    auth_mode: str,
    timeout: int,
) -> FetchResult:
    url = base_url.rstrip("/") + endpoint
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    params = {
        "symbol": symbol,
        "ticker": symbol,
        "underlying": symbol,
        "expiry": tomorrow,
        "date": tomorrow,
        "next_day": "true",
    }
    params.update(_auth_params(api_key, auth_mode))
    headers = {"Accept": "application/json"}
    headers.update(_auth_headers(api_key, auth_mode))

    resp = session.get(url, headers=headers, params=params, timeout=timeout)
    payload = None
    if "json" in resp.headers.get("content-type", "").lower():
        try:
            payload = resp.json()
        except Exception:
            payload = None
    return FetchResult(
        url=resp.url,
        status_code=resp.status_code,
        auth_mode=auth_mode,
        endpoint=endpoint,
        symbol=symbol,
        payload=payload,
        body_preview=resp.text[:500].replace("\n", " "),
    )


def _is_number(v: Any) -> bool:
    try:
        float(v)
        return True
    except Exception:
        return False


def _extract_spot(payload: Any) -> float | None:
    if isinstance(payload, dict):
        for k in ("spot", "spot_price", "price", "underlying_price", "last", "current_price"):
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
            # Direct level object
            add_level(node)

            # Numeric dict like {"5200": 12345}
            if node and all(_is_number(k) for k in node.keys()) and all(_is_number(v) for v in node.values()):
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
            # Classic endpoint often returns strike rows like:
            # [strike, gamma_vol, gamma_oi, [term_values...]]
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

    # Deduplicate by strike/type keeping max abs gamma
    best: dict[tuple[float, str], dict[str, Any]] = {}
    for lv in levels:
        key = (lv["strike"], lv["type"])
        prev = best.get(key)
        if prev is None or lv["gamma_abs"] > prev["gamma_abs"]:
            best[key] = lv
    return list(best.values())


def _rank_levels(levels: list[dict[str, Any]], spot: float | None, top_n: int) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for lv in levels:
        dist = abs(lv["strike"] - spot) if spot is not None else 0.0
        # Bias toward large absolute gamma close to current spot.
        score = lv["gamma_abs"] / (1.0 + dist)
        ranked.append(
            {
                **lv,
                "distance_to_spot": dist,
                "score": score,
            }
        )
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:top_n]


def main() -> None:
    p = argparse.ArgumentParser(description="Pull and rank ES GEX levels likely influential for next session.")
    p.add_argument("--api-key", default=os.getenv("GEXBOT_API_KEY", ""))
    p.add_argument("--base-url", default=os.getenv("GEXBOT_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument("--endpoint", default="", help="Optional known endpoint; skips endpoint probing.")
    p.add_argument("--use-classic-template", action="store_true", help="Use /{TICKER}/classic/{AGGREGATION_PERIOD}?key=... template.")
    p.add_argument("--ticker", default="ES_SPX", help="Ticker used in classic endpoint template.")
    p.add_argument("--aggregation-period", default="1", help="Aggregation period for classic template endpoint.")
    p.add_argument("--symbol", default="ES_SPX", help="Primary symbol alias to try first.")
    p.add_argument("--top-n", type=int, default=12)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--out-dir", default="projects/analysis/gexbot_data")
    args = p.parse_args()

    if not args.api_key:
        raise SystemExit("Missing API key. Pass --api-key or set GEXBOT_API_KEY.")
    if not args.base_url.startswith("http"):
        raise SystemExit(f"Invalid base URL: {args.base_url}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    auth_modes = [
        "x-api-key",
        "authorization-bearer",
        "authorization-token",
        "query-api_key",
        "query-key",
        "query-token",
    ]
    endpoints = [args.endpoint] if args.endpoint else DEFAULT_ENDPOINTS
    symbols = [args.symbol] + [s for s in DEFAULT_SYMBOL_ALIASES if s != args.symbol]

    session = requests.Session()
    fetch_log: list[dict[str, Any]] = []
    winner: FetchResult | None = None
    secrets = [args.api_key]

    # Direct documented template:
    # https://api.gexbot.com/{TICKER}/classic/{AGGREGATION_PERIOD}?key={YOUR_API_KEY}
    if args.use_classic_template:
        endpoint = f"/{args.ticker}/classic/{args.aggregation_period}"
        url = args.base_url.rstrip("/") + endpoint
        for auth_mode in auth_modes:
            try:
                resp = session.get(
                    url,
                    params=_auth_params(args.api_key, auth_mode),
                    headers={"Accept": "application/json", **_auth_headers(args.api_key, auth_mode)},
                    timeout=args.timeout,
                )
                payload = None
                if "json" in resp.headers.get("content-type", "").lower():
                    try:
                        payload = resp.json()
                    except Exception:
                        payload = None
                fetch_log.append(
                    {
                        "endpoint": endpoint,
                        "symbol": args.ticker,
                        "auth_mode": auth_mode,
                        "url": _redact_url(resp.url, secrets),
                        "status_code": resp.status_code,
                        "ok": 200 <= resp.status_code < 300,
                        "body_preview": resp.text[:500].replace("\n", " "),
                    }
                )
                if resp.status_code >= 200 and resp.status_code < 300 and payload is not None and _extract_levels(payload):
                    winner = FetchResult(
                        url=resp.url,
                        status_code=resp.status_code,
                        auth_mode=auth_mode,
                        endpoint=endpoint,
                        symbol=args.ticker,
                        payload=payload,
                        body_preview=resp.text[:500].replace("\n", " "),
                    )
                    break
            except Exception as e:
                fetch_log.append(
                    {
                        "endpoint": endpoint,
                        "symbol": args.ticker,
                        "auth_mode": auth_mode,
                        "error": str(e),
                    }
                )

    if winner is None:
        for endpoint in endpoints:
            endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
            for symbol in symbols:
                for auth_mode in auth_modes:
                    try:
                        fr = _try_fetch(
                            session=session,
                            base_url=args.base_url,
                            endpoint=endpoint,
                            symbol=symbol,
                            api_key=args.api_key,
                            auth_mode=auth_mode,
                            timeout=args.timeout,
                        )
                    except Exception as e:
                        fetch_log.append(
                            {
                                "endpoint": endpoint,
                                "symbol": symbol,
                                "auth_mode": auth_mode,
                                "error": str(e),
                            }
                        )
                        continue

                    fetch_log.append(
                        {
                            "endpoint": endpoint,
                            "symbol": symbol,
                            "auth_mode": auth_mode,
                            "url": _redact_url(fr.url, secrets),
                            "status_code": fr.status_code,
                            "ok": 200 <= fr.status_code < 300,
                            "body_preview": fr.body_preview,
                        }
                    )

                    if fr.status_code >= 200 and fr.status_code < 300 and fr.payload is not None:
                        levels = _extract_levels(fr.payload)
                        if levels:
                            winner = fr
                            break
                if winner:
                    break
            if winner:
                break

    log_path = out_dir / f"gexbot_es_levels_probe_{stamp}.json"
    log_path.write_text(json.dumps(fetch_log, indent=2), encoding="utf-8")

    if not winner:
        raise SystemExit(
            "No symbol-level GEX payload with strike/gamma levels found.\n"
            f"Saved probe log: {log_path}\n"
            "Tip: If you know your endpoint, rerun with --endpoint /your/path"
        )

    spot = _extract_spot(winner.payload)
    levels = _extract_levels(winner.payload)
    ranked = _rank_levels(levels, spot, args.top_n)

    raw_path = out_dir / f"gexbot_es_raw_{stamp}.json"
    raw_path.write_text(json.dumps(winner.payload, indent=2), encoding="utf-8")

    ranked_json_path = out_dir / f"gexbot_es_top_levels_{stamp}.json"
    ranked_json_path.write_text(
        json.dumps(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "resolved_url": _redact_url(winner.url, secrets),
                "auth_mode": winner.auth_mode,
                "symbol": winner.symbol,
                "spot": spot,
                "top_levels": ranked,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    ranked_csv_path = out_dir / f"gexbot_es_top_levels_{stamp}.csv"
    with ranked_csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["strike", "gamma_signed", "gamma_abs", "type", "distance_to_spot", "score"],
        )
        w.writeheader()
        for row in ranked:
            w.writerow(row)

    print("SUCCESS")
    print(f"Resolved URL   : {winner.url}")
    print(f"Auth mode      : {winner.auth_mode}")
    print(f"Symbol         : {winner.symbol}")
    print(f"Spot           : {spot}")
    print(f"Raw saved      : {raw_path}")
    print(f"Top JSON saved : {ranked_json_path}")
    print(f"Top CSV saved  : {ranked_csv_path}")
    print(f"Probe log      : {log_path}")


if __name__ == "__main__":
    main()
