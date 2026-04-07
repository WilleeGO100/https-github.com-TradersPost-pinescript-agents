# Migration Notes: Claude -> Codex/OpenAI

## Current State
- Primary workflow is Codex/OpenAI-first.
- Main instruction file: `CODEX.md`.
- `CLAUDE.md` is retained as a legacy pointer.
- Runtime state now defaults to `.codex/`.
- Canonical playbooks/hooks now live in `.assistant/`.

## Backward Compatibility
- Existing `.assistant/.onboarding_complete` and `.claude/.onboarding_complete` markers are recognized by startup scripts.
- Video status supports legacy `.assistant/.video_status` and `.claude/.video_status` during cleanup.
- Legacy `.claude/` playbooks and hooks remain for compatibility.

## Updated Files
- Documentation: `README.md`, `CODEX.md`, `CLAUDE.md`, `projects/README.md`
- Startup scripts: `start`, `start.sh`, `start.ps1`
- Video analyzer: `tools/video-analyzer.py`
- Status and ignore rules: `.assistant/statusline.sh`, `.claude/statusline.sh`, `.gitignore`

## Recommended Usage
1. Activate `.venv`.
2. Run `./start.ps1` on Windows or `./start` on macOS/Linux.
3. Build scripts in `projects/`.
4. Use `tools/video-analyzer.py` when starting from YouTube strategy videos.
