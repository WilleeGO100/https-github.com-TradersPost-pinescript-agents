# Pine Script Development Assistant - Codex Instructions

## Purpose
This repository is a Codex/OpenAI-first Pine Script workspace for building professional TradingView indicators and strategies.

Primary assets:
- `docs/pinescript-v6/` for language and platform rules
- `templates/` for starter patterns
- `examples/` for reference implementations
- `tools/video-analyzer.py` for YouTube strategy extraction
- `projects/` for user scripts

## Core Rules

### Pine Script line wrapping (critical)
- Keep ternary operators (`? :`) on one line when possible.
- For wrapped expressions, continuation lines must be indented more than the starting line.
- Avoid introducing "end of line without line continuation" errors.

### Script quality baseline
- Start every script with `//@version=6`.
- Group inputs and include clear tooltips.
- Handle `na` values and edge bars.
- Avoid repainting unless explicitly intended and documented.
- Keep calculations efficient and readable.

## Standard Codex Workflow
1. Clarify scope and constraints.
2. Implement in `projects/<project-name>.pine`.
3. Run a debugging pass (syntax, repainting, signal conditions).
4. Run a performance pass (security call count, loop/drawing usage).
5. Validate visually in TradingView and iterate.
6. Prepare publish-ready headers and documentation.

## Video Analysis Workflow

When given a YouTube URL, run local analysis:

```bash
python tools/video-analyzer.py "<youtube_url>"
```

Optional modes:

```bash
python tools/video-analyzer.py "<youtube_url>" --whisper
python tools/video-analyzer.py "<youtube_url>" --whisper --model medium
python tools/video-analyzer.py "<youtube_url>" --json
```

Then:
1. Review extracted strategy components from `projects/analysis/`.
2. Confirm or refine assumptions with the user.
3. Implement Pine Script from the approved specification.

## Role Playbook Mapping

The canonical `.assistant/skills/` directory contains reusable playbooks. Legacy compatibility remains in `.claude/skills/`.

- `pine-visualizer`: break ideas into implementable components
- `pine-developer`: implement production Pine Script v6 code
- `pine-debugger`: diagnose/fix errors and repainting issues
- `pine-backtester`: add performance metrics and evaluation
- `pine-optimizer`: improve speed, UX, and maintainability
- `pine-manager`: coordinate complex multi-step builds
- `pine-publisher`: prepare publication-ready output

## Suggested Prompt Patterns

- "Create a Pine v6 indicator for `<logic>` with grouped inputs, alerts, and non-repainting signals."
- "Debug `projects/<file>.pine` for repainting and `na` handling issues."
- "Optimize `projects/<file>.pine` to reduce `request.security()` overhead."
- "Use the video analysis JSON to implement a complete strategy in Pine v6."

## Operational Notes
- Keep user deliverables in `projects/`.
- Runtime state is stored in `.codex/` (with backward compatibility for legacy `.assistant/` and `.claude/` markers).
- Use templates/examples when helpful, but prioritize user requirements.
- If legacy Claude files conflict with this document, follow this document.
