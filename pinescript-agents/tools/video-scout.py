#!/usr/bin/env python3
"""
Discover and score YouTube strategy videos for automated Pine pipeline runs.
Writes/updates queue state in projects/analysis/pipeline_state.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


def check_and_install_packages() -> None:
    packages = {
        "yt_dlp": "yt-dlp",
        "youtube_transcript_api": "youtube-transcript-api",
    }
    missing = []
    for module, pip_name in packages.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name)
    if missing:
        import subprocess

        print(f"Installing missing packages: {', '.join(missing)}")
        for pkg in missing:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])


check_and_install_packages()

import yt_dlp  # noqa: E402
from youtube_transcript_api import YouTubeTranscriptApi  # noqa: E402


STATE_DEFAULT = Path("projects/analysis/pipeline_state.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(path: Path) -> Dict:
    if not path.exists():
        return {
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "queue": [],
            "history": [],
        }
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: Path, state: Dict) -> None:
    state["updated_at"] = now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def captions_available(video_id: str) -> bool:
    try:
        api = YouTubeTranscriptApi()
        _ = api.list(video_id)
        return True
    except Exception:
        return False


def score_entry(entry: Dict, min_duration: int, max_duration: int) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []

    title = (entry.get("title") or "").lower()
    duration = int(entry.get("duration") or 0)
    views = int(entry.get("view_count") or 0)

    if min_duration <= duration <= max_duration:
        score += 2
        reasons.append("good_duration")
    elif 0 < duration < min_duration:
        score -= 2
        reasons.append("too_short")
    elif duration > max_duration:
        score -= 1
        reasons.append("too_long")

    if views >= 100_000:
        score += 2
        reasons.append("high_views")
    elif views >= 10_000:
        score += 1
        reasons.append("medium_views")

    for token in ["strategy", "setup", "rules", "breakout", "entry", "exit", "risk"]:
        if token in title:
            score += 1
            reasons.append(f"title:{token}")

    if re.search(r"\b(live|stream|music|podcast|reaction|motivation)\b", title):
        score -= 2
        reasons.append("low_structure_title")

    return score, reasons


def discover(query: str, per_query: int) -> List[Dict]:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }
    search_term = f"ytsearch{per_query}:{query}"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_term, download=False)
    return info.get("entries", []) if isinstance(info, dict) else []


def main() -> int:
    parser = argparse.ArgumentParser(description="Scout and queue YouTube strategy videos.")
    parser.add_argument(
        "--queries",
        default="opening range breakout strategy,nq futures strategy,es futures strategy,price action strategy",
        help="Comma-separated search queries.",
    )
    parser.add_argument("--per-query", type=int, default=8, help="Videos fetched per query.")
    parser.add_argument("--min-duration", type=int, default=8 * 60, help="Minimum duration in seconds.")
    parser.add_argument("--max-duration", type=int, default=35 * 60, help="Maximum duration in seconds.")
    parser.add_argument("--min-score", type=int, default=4, help="Minimum score to queue.")
    parser.add_argument("--max-add", type=int, default=10, help="Maximum videos to add per run.")
    parser.add_argument("--state", default=str(STATE_DEFAULT), help="Pipeline state JSON path.")
    args = parser.parse_args()

    state_path = Path(args.state)
    state = load_state(state_path)

    seen_ids = {item.get("video_id") for item in state.get("queue", [])}
    seen_ids.update(item.get("video_id") for item in state.get("history", []))

    added = 0
    candidates: List[Dict] = []
    queries = [q.strip() for q in args.queries.split(",") if q.strip()]

    for query in queries:
        print(f"Searching: {query}")
        for entry in discover(query, args.per_query):
            video_id = entry.get("id")
            if not video_id or video_id in seen_ids:
                continue

            base_score, reasons = score_entry(entry, args.min_duration, args.max_duration)
            has_caps = captions_available(video_id)
            if has_caps:
                base_score += 2
                reasons.append("captions_available")
            else:
                reasons.append("captions_missing")

            url = f"https://www.youtube.com/watch?v={video_id}"
            row = {
                "video_id": video_id,
                "url": url,
                "title": entry.get("title", ""),
                "channel": entry.get("uploader", ""),
                "duration": int(entry.get("duration") or 0),
                "views": int(entry.get("view_count") or 0),
                "score": base_score,
                "reasons": reasons,
                "status": "queued",
                "queued_at": now_iso(),
            }
            candidates.append(row)

    candidates.sort(key=lambda x: x["score"], reverse=True)

    for row in candidates:
        if row["score"] < args.min_score:
            continue
        if added >= args.max_add:
            break
        state["queue"].append(row)
        seen_ids.add(row["video_id"])
        added += 1

    save_state(state_path, state)

    print(f"Queued {added} video(s). State: {state_path}")
    if added:
        for row in state["queue"][-added:]:
            print(f"  + {row['video_id']} score={row['score']} {row['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
