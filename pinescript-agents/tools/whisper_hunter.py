import json
import yt_dlp
from collections import defaultdict

# Setup Parameters
SEARCH_QUERY = "Pinescript crypto trading strategies tutorial"
VIDEO_LIMIT = 10
MIN_DURATION = 600  # 10 minutes
MAX_DURATION = 2100  # 35 minutes

# Semantic keyword filtering
STRATEGY_KEYWORDS = {
    "Mean Reversion": [
        "mean reversion",
        "rsi",
        "bollinger",
        "oscillator",
        "overbought",
    ],
    "Breakout": ["breakout", "support", "resistance", "smc", "liquidity"],
    "Trend Following": ["trend", "macd", "ema", "moving average", "crossover"],
}


def get_videos():
    ydl_opts = {
        "quiet": True,
        "extract_flat": False,
        "ignoreerrors": True,
        "js_runtimes": {"node": {}},
        "remote_components": {"ejs:github"},
        "cachedir": ".yt-dlp-cache",
    }

    print("Hunting for high-signal videos... This takes about 30 seconds.")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(f"ytsearch50:{SEARCH_QUERY}", download=False)

        video_candidates = []
        for entry in result.get("entries", []):
            if not entry:
                continue

            duration = entry.get("duration", 0)
            title = entry.get("title", "")
            subtitles = entry.get("subtitles", {})
            auto_subs = entry.get("automatic_captions", {})

            # Semantic Sorting
            title_lower = title.lower()
            strategy_type = "Other"
            for strat, kws in STRATEGY_KEYWORDS.items():
                if any(kw in title_lower for kw in kws):
                    strategy_type = strat
                    break

            # The Whisper Audio Filter
            if MIN_DURATION <= duration <= MAX_DURATION:
                has_english_subs = "en" in subtitles or "en" in auto_subs

                video_candidates.append(
                    {
                        "title": title,
                        "url": entry.get("webpage_url", ""),
                        "channel": entry.get("uploader", ""),
                        "strategy_type": strategy_type,
                        "whisper_friendly_subs": has_english_subs,
                    }
                )

        return video_candidates


def main():
    video_candidates = get_videos()

    selected_videos = []
    strategy_count = defaultdict(int)

    # Max 3 per strategy rule
    for video in video_candidates:
        strat = video["strategy_type"]

        if strategy_count[strat] < 3:
            selected_videos.append(video)
            strategy_count[strat] += 1

        if len(selected_videos) >= VIDEO_LIMIT:
            break

    print(f"Found {len(selected_videos)} highly optimized videos. Saving to JSON...")

    with open("whisper_targets.json", "w") as f:
        json.dump(selected_videos, f, indent=4)

    print("Done! File saved as whisper_targets.json")


if __name__ == "__main__":
    main()
