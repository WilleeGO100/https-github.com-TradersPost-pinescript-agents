#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


DEFAULT_BASE_URL = "https://api.gexbot.com"
DEFAULT_CANDIDATE_ENDPOINTS = [
    "/tickers",
    "/v1/tickers",
    "/api/tickers",
    "/gex",
    "/v1/gex",
    "/api/gex",
    "/gamma",
    "/v1/gamma",
    "/api/gamma",
]


@dataclass
class ProbeResult:
    auth_mode: str
    url: str
    status_code: int
    ok: bool
    content_type: str
    body_preview: str
    json_body: Any | None


def _build_auth_headers(api_key: str, mode: str) -> dict[str, str]:
    if mode == "x-api-key":
        return {"X-API-Key": api_key}
    if mode == "authorization-bearer":
        return {"Authorization": f"Bearer {api_key}"}
    if mode == "authorization-token":
        return {"Authorization": api_key}
    return {}


def _build_auth_params(api_key: str, mode: str) -> dict[str, str]:
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


def _probe(
    session: requests.Session,
    base_url: str,
    endpoint: str,
    api_key: str,
    auth_mode: str,
    timeout: int,
) -> ProbeResult:
    url = base_url.rstrip("/") + endpoint
    headers = {"Accept": "application/json"}
    headers.update(_build_auth_headers(api_key, auth_mode))
    params = _build_auth_params(api_key, auth_mode)

    resp = session.get(url, headers=headers, params=params, timeout=timeout)
    content_type = resp.headers.get("content-type", "")
    text = resp.text[:400].replace("\n", " ")
    parsed = None
    if "json" in content_type.lower():
        try:
            parsed = resp.json()
        except Exception:
            parsed = None
    return ProbeResult(
        auth_mode=auth_mode,
        url=resp.url,
        status_code=resp.status_code,
        ok=resp.ok,
        content_type=content_type,
        body_preview=text,
        json_body=parsed,
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Pull GEX data from GEXBot API and save JSON.")
    p.add_argument("--api-key", default=os.getenv("GEXBOT_API_KEY", ""), help="GEXBot API key (or set GEXBOT_API_KEY).")
    p.add_argument("--base-url", default=os.getenv("GEXBOT_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument("--endpoint", default="", help="Known endpoint (e.g. /tickers). If omitted, script probes candidates.")
    p.add_argument("--symbol", default="", help="Optional symbol to pass as ?symbol=...")
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--out-dir", default="projects/analysis/gexbot_data")
    args = p.parse_args()

    if not args.api_key:
        raise SystemExit("Missing API key. Pass --api-key or set GEXBOT_API_KEY.")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    auth_modes = [
        "x-api-key",
        "authorization-bearer",
        "authorization-token",
        "query-api_key",
        "query-key",
        "query-token",
    ]

    endpoints = [args.endpoint] if args.endpoint else DEFAULT_CANDIDATE_ENDPOINTS
    session = requests.Session()
    best: ProbeResult | None = None
    probe_log: list[dict[str, Any]] = []
    secrets = [args.api_key]

    for ep in endpoints:
        ep = ep if ep.startswith("/") else f"/{ep}"
        for mode in auth_modes:
            try:
                result = _probe(session, args.base_url, ep, args.api_key, mode, args.timeout)
            except Exception as e:
                probe_log.append(
                    {"endpoint": ep, "auth_mode": mode, "error": str(e)}
                )
                continue

            probe_log.append(
                {
                    "endpoint": ep,
                    "auth_mode": mode,
                    "url": _redact_url(result.url, secrets),
                    "status_code": result.status_code,
                    "ok": result.ok,
                    "content_type": result.content_type,
                    "body_preview": result.body_preview,
                }
            )

            if result.ok and result.status_code < 300:
                best = result
                break
        if best:
            break

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    probe_path = out_dir / f"gexbot_probe_{stamp}.json"
    probe_path.write_text(json.dumps(probe_log, indent=2), encoding="utf-8")

    if not best:
        raise SystemExit(
            f"No successful endpoint/auth combination found.\nSaved probe log: {probe_path}"
        )

    data_obj: Any = best.json_body if best.json_body is not None else {"raw": best.body_preview}
    data_path = out_dir / f"gexbot_data_{stamp}.json"
    data_path.write_text(json.dumps(data_obj, indent=2), encoding="utf-8")

    print("SUCCESS")
    print(f"Resolved URL   : {best.url}")
    print(f"Auth mode      : {best.auth_mode}")
    print(f"Status         : {best.status_code}")
    print(f"Data saved     : {data_path}")
    print(f"Probe log saved: {probe_path}")


if __name__ == "__main__":
    main()
