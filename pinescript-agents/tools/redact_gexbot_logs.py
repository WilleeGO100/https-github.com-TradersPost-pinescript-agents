#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SENSITIVE_QUERY_KEYS = {"api_key", "key", "token"}


def _redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        q = parse_qsl(parts.query, keep_blank_values=True)
        redacted = [(k, "REDACTED" if k.lower() in SENSITIVE_QUERY_KEYS else v) for k, v in q]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(redacted), parts.fragment))
    except Exception:
        return url


def _walk(node: Any) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in {"url", "resolved_url"} and isinstance(v, str):
                out[k] = _redact_url(v)
            else:
                out[k] = _walk(v)
        return out
    if isinstance(node, list):
        return [_walk(v) for v in node]
    return node


def main() -> None:
    p = argparse.ArgumentParser(description="Redact GEXBot API keys/tokens from saved JSON logs.")
    p.add_argument("--dir", default="projects/analysis/gexbot_data", help="Directory containing JSON logs.")
    p.add_argument("--in-place", action="store_true", help="Rewrite files in-place (default is dry-run).")
    args = p.parse_args()

    root = Path(args.dir)
    if not root.exists():
        raise SystemExit(f"Directory not found: {root}")

    changed = 0
    for path in sorted(root.glob("*.json")):
        try:
            original = path.read_text(encoding="utf-8")
            data = json.loads(original)
        except Exception:
            continue

        redacted = _walk(data)
        redacted_text = json.dumps(redacted, indent=2, ensure_ascii=False) + "\n"
        if redacted_text != original and redacted_text != original + "\n":
            changed += 1
            if args.in_place:
                path.write_text(redacted_text, encoding="utf-8")
            else:
                print(f"WOULD_REDACT {path}")

    if args.in_place:
        print(f"REDACTED_FILES {changed}")
    else:
        print(f"WOULD_REDACT_FILES {changed} (dry-run)")


if __name__ == "__main__":
    main()

