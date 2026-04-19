#!/usr/bin/env python3
"""
Autonomous queue runner:
1) Reads projects/analysis/pipeline_state.json queue
2) Runs video-analyzer.py
3) Runs analysis-to-pinescript.py
4) Writes output/status back to state file
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional


STATE_DEFAULT = Path("projects/analysis/pipeline_state.json")
VIDEO_ANALYZER = Path("pinescript-agents/tools/video-analyzer.py")
ANALYSIS_TO_PINE = Path("pinescript-agents/tools/analysis-to-pinescript.py")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(path: Path) -> Dict:
    if not path.exists():
        return {"created_at": now_iso(), "updated_at": now_iso(), "queue": [], "history": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: Path, state: Dict) -> None:
    state["updated_at"] = now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def extract_json_blob(stdout: str) -> Optional[Dict]:
    if not stdout:
        return None
    text = stdout.strip()
    for i in range(len(text)):
        if text[i] != "{":
            continue
        candidate = text[i:]
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run autonomous analysis -> Pine generation pipeline.")
    parser.add_argument("--state", default=str(STATE_DEFAULT), help="Pipeline state JSON path.")
    parser.add_argument("--max-videos", type=int, default=3, help="Max queued videos to process this run.")
    parser.add_argument("--model", default="medium", choices=["tiny", "base", "small", "medium", "large"])
    parser.add_argument("--whisper", action="store_true", help="Force Whisper mode for analysis.")
    parser.add_argument("--retry-failed", action="store_true", help="Also process items with failed status.")
    parser.add_argument(
        "--cookies-from-browser",
        default="",
        help="Pass browser cookies to yt-dlp (e.g. chrome or chrome:Default).",
    )
    parser.add_argument(
        "--cookies",
        default="",
        help="Path to cookies.txt file for yt-dlp.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print what would run without executing.")
    args = parser.parse_args()

    state_path = Path(args.state)
    state = load_state(state_path)
    queue = state.get("queue", [])

    eligible_statuses = {"queued"}
    if args.retry_failed:
        eligible_statuses.add("failed")
    queued_items = [item for item in queue if item.get("status") in eligible_statuses]
    if not queued_items:
        print("No queued videos.")
        return 0

    processed_count = 0
    for item in queued_items:
        if processed_count >= args.max_videos:
            break

        video_id = item.get("video_id")
        url = item.get("url")
        if not video_id or not url:
            item["status"] = "failed"
            item["error"] = "missing_video_id_or_url"
            continue

        print(f"Processing {video_id}: {url}")
        item["status"] = "running"
        item["started_at"] = now_iso()
        save_state(state_path, state)

        analyzer_cmd = [sys.executable, str(VIDEO_ANALYZER), url, "--json"]
        if args.whisper:
            analyzer_cmd.extend(["--whisper", "--model", args.model])
        if args.cookies_from_browser:
            analyzer_cmd.extend(["--cookies-from-browser", args.cookies_from_browser])
        if args.cookies:
            analyzer_cmd.extend(["--cookies", args.cookies])

        if args.dry_run:
            print("DRY RUN analyzer:", " ".join(analyzer_cmd))
            item["status"] = "queued"
            continue

        analyzer_res = run_cmd(analyzer_cmd)
        payload = extract_json_blob(analyzer_res.stdout)
        if analyzer_res.returncode != 0 or not payload or not payload.get("success"):
            item["status"] = "failed"
            item["finished_at"] = now_iso()
            item["error"] = (
                payload.get("error")
                if isinstance(payload, dict)
                else analyzer_res.stderr.strip() or "analyzer_failed"
            )
            state["history"].append(
                {
                    "video_id": video_id,
                    "url": url,
                    "status": "failed",
                    "error": item["error"],
                    "finished_at": item["finished_at"],
                }
            )
            save_state(state_path, state)
            continue

        analysis_file = payload.get("saved_to")
        if not analysis_file:
            item["status"] = "failed"
            item["finished_at"] = now_iso()
            item["error"] = "analysis_path_missing"
            save_state(state_path, state)
            continue

        pine_output = Path("projects/analysis") / f"{video_id}-auto-breakout.pine"
        pine_cmd = [
            sys.executable,
            str(ANALYSIS_TO_PINE),
            analysis_file,
            "--output",
            str(pine_output),
        ]
        pine_res = run_cmd(pine_cmd)
        if pine_res.returncode != 0:
            item["status"] = "failed"
            item["finished_at"] = now_iso()
            item["error"] = pine_res.stderr.strip() or pine_res.stdout.strip() or "pine_generation_failed"
            state["history"].append(
                {
                    "video_id": video_id,
                    "url": url,
                    "status": "failed",
                    "analysis_file": analysis_file,
                    "error": item["error"],
                    "finished_at": item["finished_at"],
                }
            )
            save_state(state_path, state)
            continue

        item["status"] = "completed"
        item["analysis_file"] = analysis_file
        item["pine_file"] = str(pine_output)
        item["finished_at"] = now_iso()
        state["history"].append(
            {
                "video_id": video_id,
                "url": url,
                "status": "completed",
                "analysis_file": analysis_file,
                "pine_file": str(pine_output),
                "finished_at": item["finished_at"],
            }
        )
        save_state(state_path, state)
        processed_count += 1

    print(f"Run complete. Processed: {processed_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
