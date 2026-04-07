# Pine Script Development Assistant for Codex

A Pine Script development environment for building professional TradingView indicators and strategies with Codex/OpenAI.

Use this repo as a production workspace with:
- Pine Script v6 documentation
- Reusable templates and examples
- A YouTube video analyzer that extracts strategy logic

## Quick Start

1. Clone and enter the project
```bash
git clone https://github.com/TradersPost/pinescript-agents.git
cd pinescript-agents
```

2. Create and activate a virtual environment

Windows PowerShell:
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install dependencies
```bash
pip install -r requirements.txt
```

4. Optional: install FFmpeg for Whisper fallback transcription
- Windows: `winget install Gyan.FFmpeg`
- macOS: `brew install ffmpeg`
- Ubuntu/Debian: `sudo apt install ffmpeg`

5. Start a guided project session
- macOS/Linux: `./start`
- Windows PowerShell: `./start.ps1`

## Codex Workflow

1. Open this folder in Codex.
2. Describe what you want to build.
3. Codex drafts or edits a Pine script in `projects/`.
4. Iterate with debugging, backtesting, and optimization passes.

Example requests:
- `Create an RSI divergence indicator with alerts and tooltips.`
- `Build a Bollinger mean reversion strategy with stop loss and take profit.`
- `Debug repainting in projects/my-strategy.pine.`
- `Optimize this script for fewer security() calls.`

## Video Analysis Workflow

Analyze strategy videos before coding:

```bash
python tools/video-analyzer.py "https://youtube.com/watch?v=..."
```

Useful options:
```bash
# Force Whisper transcription
python tools/video-analyzer.py "https://youtube.com/watch?v=..." --whisper

# Use a larger Whisper model
python tools/video-analyzer.py "https://youtube.com/watch?v=..." --whisper --model medium

# Raw JSON output
python tools/video-analyzer.py "https://youtube.com/watch?v=..." --json
```

Output is stored in `projects/analysis/`.

## Skill Playbooks (Codex Prompt Mapping)

This repo includes role playbooks under `.assistant/skills/` (with legacy compatibility in `.claude/skills/`). In Codex, treat them as reusable guidance and invoke them explicitly in your prompt.

- `pine-visualizer`: "Break this trading idea into implementable Pine components first."
- `pine-developer`: "Implement production-ready Pine Script v6 code now."
- `pine-debugger`: "Diagnose this script error and add debugging instrumentation."
- `pine-backtester`: "Add backtesting metrics and performance analysis."
- `pine-optimizer`: "Optimize this script for speed and clarity."
- `pine-manager`: "Plan and execute this as a multi-step trading system project."
- `pine-publisher`: "Prepare this script for TradingView publication."

## Project Structure

```text
pinescript-agents/
├── .codex/               # Runtime state files for Codex workflows
├── .assistant/            # Canonical playbooks and hook assets
├── .claude/               # Legacy compatibility copy
├── docs/                  # Pine Script docs and workflows
├── templates/             # Starter templates
├── examples/              # Reference scripts
├── projects/              # Your working scripts
├── tools/                 # Utilities, including video analyzer
├── requirements.txt
└── README.md
```

## Recommended Build Cycle

1. Scope requirements and edge cases.
2. Build initial script in `projects/<name>.pine`.
3. Run a debug pass (na handling, repaint checks, alert logic).
4. Run a performance pass (security calls, loops, drawing limits).
5. Validate visually in TradingView across multiple timeframes.
6. Prepare publish-ready headers, inputs, and documentation.

## Templates and Examples

- Templates: `templates/`
- Examples: `examples/`
- Pine docs: `docs/pinescript-v6/`
- Codex instructions: `CODEX.md`
- Migration details: `MIGRATION.md`

## Best Practices

- Start every script with `//@version=6`
- Avoid repainting unless explicitly intended and documented
- Group inputs and provide clear tooltips
- Handle `na` values and edge bars safely
- Keep calculations efficient and readable
- Test on different symbols and timeframes

## License

MIT License
