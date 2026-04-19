#!/usr/bin/env python3
"""
Convert video analysis JSON into a Pine Script v6 strategy scaffold.

This converter uses pine-mcp's local language reference JSON to validate
that generated Pine function names exist before writing output.
"""

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def load_json(path: Path) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_first_int(text: str) -> Optional[int]:
    match = re.search(r"(\d+)", text or "")
    return int(match.group(1)) if match else None


def infer_opening_range_minutes(spec: Dict) -> int:
    for tf in spec.get("timeframes", []):
        tf_minutes = re.search(r"(\d+)\s*minute", tf.lower())
        if tf_minutes:
            return int(tf_minutes.group(1))
    return 30


def infer_ema_lengths(spec: Dict) -> Tuple[int, int]:
    for param in spec.get("parameters", []):
        if param.get("type") == "ma_lengths":
            values = []
            for v in param.get("values", []):
                iv = extract_first_int(str(v))
                if iv:
                    values.append(iv)
            values = sorted(set(values))
            if len(values) >= 2:
                return values[0], values[1]
            if len(values) == 1:
                return values[0], max(values[0] + 13, 21)
    return 8, 21


def infer_booleans(spec: Dict) -> Dict[str, bool]:
    entry = " ".join(spec.get("implementation", {}).get("entry_logic", [])).lower()
    exits = " ".join(spec.get("implementation", {}).get("exit_logic", [])).lower()
    risk = " ".join(spec.get("implementation", {}).get("risk_rules", [])).lower()
    full = " ".join([entry, exits, risk])
    return {
        "use_retest_entry": "retest" in full,
        "move_to_be": ("break even" in full) or ("breakeven" in full),
    }


def sanitize_title(raw_title: str) -> str:
    base = raw_title or "Video Derived ORB Strategy"
    base = re.sub(r"\s+", " ", base).strip()
    if len(base) > 60:
        base = base[:57] + "..."
    return base.replace('"', "'")


def build_strategy_pine(
    script_title: str,
    opening_range_minutes: int,
    fast_ema: int,
    slow_ema: int,
    use_retest_entry: bool,
    move_to_be: bool,
    source_file: str,
) -> str:
    retest_logic = (
        "retestLong = low <= orbHigh and close > orbHigh\n"
        "retestShort = high >= orbLow and close < orbLow\n"
        "longTrigger = longBreakout and (not requireRetest or retestLong)\n"
        "shortTrigger = shortBreakout and (not requireRetest or retestShort)"
        if use_retest_entry
        else
        "longTrigger = longBreakout\nshortTrigger = shortBreakout"
    )

    be_logic = (
        "if moveStopToBreakEven and strategy.position_size > 0 and high >= longTp1\n"
        "    strategy.exit('L-SL-BE', from_entry='Long', stop=strategy.position_avg_price)\n"
        "if moveStopToBreakEven and strategy.position_size < 0 and low <= shortTp1\n"
        "    strategy.exit('S-SL-BE', from_entry='Short', stop=strategy.position_avg_price)"
        if move_to_be
        else "// Break-even move disabled by inferred rules."
    )

    return f"""//@version=6
strategy("{script_title}", overlay=true, initial_capital=100000, pyramiding=0, process_orders_on_close=true, default_qty_type=strategy.percent_of_equity, default_qty_value=10)

// Generated from analysis JSON:
// {source_file}
// Model assumptions:
// 1) Opening range breakout on first session window.
// 2) Optional retest confirmation before entry.
// 3) EMA trend filter ({fast_ema}/{slow_ema}), plus fixed-R partial exits.

groupSession = "Session"
groupSignals = "Signal Rules"
groupRisk = "Risk"
groupDisplay = "Display"

sessionInput = input.session("0930-1600", "Trading Session", group=groupSession, tooltip="Session used to define opening range.")
orbMinutes = input.int({opening_range_minutes}, "Opening Range Minutes", minval=5, maxval=120, group=groupSession)

fastEmaLen = input.int({fast_ema}, "Fast EMA", minval=1, group=groupSignals)
slowEmaLen = input.int({slow_ema}, "Slow EMA", minval=1, group=groupSignals)
requireRetest = input.bool({str(use_retest_entry).lower()}, "Require Retest Confirmation", group=groupSignals, tooltip="If enabled, price must retest the breakout level before entry.")

riskPct = input.float(0.35, "Risk % (vs entry)", minval=0.05, step=0.05, group=groupRisk)
tp1R = input.float(1.0, "TP1 (R multiple)", minval=0.5, step=0.25, group=groupRisk)
tp2R = input.float(2.0, "TP2 (R multiple)", minval=1.0, step=0.25, group=groupRisk)
moveStopToBreakEven = input.bool({str(move_to_be).lower()}, "Move Stop To Break-Even After TP1", group=groupRisk)

showLevels = input.bool(true, "Show ORB Levels", group=groupDisplay)
showSignals = input.bool(true, "Show Signal Markers", group=groupDisplay)

inSession = not na(time(timeframe.period, sessionInput))
newSession = inSession and not inSession[1]
sessionEnd = not inSession and inSession[1]

var int orbStartTs = na
var float orbHigh = na
var float orbLow = na
var bool orbLocked = false
var bool tradedThisSession = false

if newSession
    orbStartTs := time
    orbHigh := high
    orbLow := low
    orbLocked := false
    tradedThisSession := false

if inSession and not orbLocked
    orbHigh := na(orbHigh) ? high : math.max(orbHigh, high)
    orbLow := na(orbLow) ? low : math.min(orbLow, low)
    orbLocked := time >= orbStartTs + orbMinutes * 60 * 1000

if sessionEnd
    orbLocked := false

fastEma = ta.ema(close, fastEmaLen)
slowEma = ta.ema(close, slowEmaLen)
trendLong = fastEma > slowEma
trendShort = fastEma < slowEma

longBreakout = orbLocked and trendLong and close > orbHigh and close[1] <= orbHigh
shortBreakout = orbLocked and trendShort and close < orbLow and close[1] >= orbLow

{retest_logic}

canTrade = inSession and orbLocked and not tradedThisSession and strategy.position_size == 0

if canTrade and longTrigger
    strategy.entry("Long", strategy.long)
    tradedThisSession := true

if canTrade and shortTrigger
    strategy.entry("Short", strategy.short)
    tradedThisSession := true

longRisk = strategy.position_avg_price * (riskPct / 100.0)
shortRisk = strategy.position_avg_price * (riskPct / 100.0)

longStop = strategy.position_avg_price - longRisk
longTp1 = strategy.position_avg_price + longRisk * tp1R
longTp2 = strategy.position_avg_price + longRisk * tp2R

shortStop = strategy.position_avg_price + shortRisk
shortTp1 = strategy.position_avg_price - shortRisk * tp1R
shortTp2 = strategy.position_avg_price - shortRisk * tp2R

if strategy.position_size > 0
    strategy.exit("L-TP1", from_entry="Long", stop=longStop, limit=longTp1, qty_percent=50)
    strategy.exit("L-TP2", from_entry="Long", stop=longStop, limit=longTp2, qty_percent=50)

if strategy.position_size < 0
    strategy.exit("S-TP1", from_entry="Short", stop=shortStop, limit=shortTp1, qty_percent=50)
    strategy.exit("S-TP2", from_entry="Short", stop=shortStop, limit=shortTp2, qty_percent=50)

{be_logic}

plot(showLevels and orbLocked ? orbHigh : na, "ORB High", color=color.new(color.green, 0), linewidth=2, style=plot.style_linebr)
plot(showLevels and orbLocked ? orbLow : na, "ORB Low", color=color.new(color.red, 0), linewidth=2, style=plot.style_linebr)
plot(fastEma, "Fast EMA", color=color.new(color.blue, 0))
plot(slowEma, "Slow EMA", color=color.new(color.orange, 0))

plotshape(showSignals and longTrigger and canTrade, title="Long Trigger", style=shape.triangleup, location=location.belowbar, color=color.new(color.green, 0), size=size.tiny, text="L")
plotshape(showSignals and shortTrigger and canTrade, title="Short Trigger", style=shape.triangledown, location=location.abovebar, color=color.new(color.red, 0), size=size.tiny, text="S")

alertcondition(longTrigger and canTrade, "Long ORB Trigger", "Long ORB trigger detected")
alertcondition(shortTrigger and canTrade, "Short ORB Trigger", "Short ORB trigger detected")
"""


def load_pine_reference_function_names(pine_mcp_root: Path) -> List[str]:
    ref_path = pine_mcp_root / "data" / "reference" / "language-reference.json"
    ref_json = load_json(ref_path)
    return sorted({entry.get("name", "") for entry in ref_json.get("functions", {}).values() if entry.get("name")})


def validate_required_functions(known_function_names: List[str]) -> List[str]:
    required = [
        "strategy",
        "input.int",
        "input.float",
        "input.bool",
        "input.session",
        "ta.ema",
        "math.max",
        "math.min",
        "plot",
        "plotshape",
        "alertcondition",
        "strategy.entry",
        "strategy.exit",
    ]
    known = set(known_function_names)
    return [name for name in required if name not in known]


def default_output_path(video_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "", video_id or "analysis")
    return Path("pinescript-agents") / "projects" / "generated" / f"{safe_id}-strategy.pine"


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert analysis JSON into Pine Script strategy scaffold.")
    parser.add_argument("analysis_json", help="Path to analysis_*.json file")
    parser.add_argument(
        "--pine-mcp-root",
        default=r"C:\Python312\pine-mcp",
        help="Path to pine-mcp repository root",
    )
    parser.add_argument(
        "--output",
        help="Output .pine file path (default: pinescript-agents/projects/generated/<video_id>-strategy.pine)",
    )
    args = parser.parse_args()

    analysis_path = Path(args.analysis_json)
    if not analysis_path.exists():
        print(f"Error: analysis file not found: {analysis_path}")
        return 1

    pine_mcp_root = Path(args.pine_mcp_root)
    if not pine_mcp_root.exists():
        print(f"Error: pine-mcp root not found: {pine_mcp_root}")
        return 1

    analysis = load_json(analysis_path)
    if not analysis.get("success"):
        print("Error: analysis JSON indicates unsuccessful analysis.")
        return 1

    spec = analysis.get("spec", {})
    video_id = analysis.get("video_id", "analysis")
    title = sanitize_title(spec.get("video_info", {}).get("title", "Video Derived ORB Strategy"))
    opening_range_minutes = infer_opening_range_minutes(spec)
    fast_ema, slow_ema = infer_ema_lengths(spec)
    flags = infer_booleans(spec)

    known_function_names = load_pine_reference_function_names(pine_mcp_root)
    missing = validate_required_functions(known_function_names)
    if missing:
        print("Error: required Pine functions missing in pine-mcp reference:")
        for name in missing:
            print(f"  - {name}")
        return 1

    script_name = f"{title} [Auto ORB]"
    pine_code = build_strategy_pine(
        script_title=script_name,
        opening_range_minutes=opening_range_minutes,
        fast_ema=fast_ema,
        slow_ema=slow_ema,
        use_retest_entry=flags["use_retest_entry"],
        move_to_be=flags["move_to_be"],
        source_file=str(analysis_path),
    )

    output_path = Path(args.output) if args.output else default_output_path(video_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(pine_code, encoding="utf-8")

    print(f"Generated Pine script: {output_path}")
    print(f"Opening range minutes: {opening_range_minutes}")
    print(f"EMA lengths: {fast_ema}/{slow_ema}")
    print(f"Require retest: {flags['use_retest_entry']}")
    print(f"Move stop to break-even: {flags['move_to_be']}")
    print("pine-mcp validation: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
