# Changelog

All notable changes to PineScript Agents will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.0] - 2026-04-06
### Changed
- Migrated canonical playbook/hook assets to `.assistant/` with `.claude/` retained for compatibility.
- Migrated runtime state to `.codex/` with compatibility fallback for legacy markers.
- Updated startup scripts, status handling, and docs for Codex/OpenAI-first workflow.

## [1.3.0] - 2025-12-18

### Added
- **YouTube Video Analysis**: Analyze trading strategy videos and auto-generate Pine Scripts
  - Uses YouTube captions (fast) with Whisper fallback
  - Extracts indicators, patterns, entry/exit conditions
  - Generates implementation specifications
  - Caches transcripts for instant re-analysis
- **Project Statusline**: Custom status bar showing version, project count, and skills
- **Requirements file**: `requirements.txt` for video analysis dependencies
- **Daily Bias + FVG Strategy**: Example strategy generated from video analysis

### Changed
- Migrated from `.claude/agents/` to `.claude/skills/` system
- Skills now auto-activate based on user request context
- Updated documentation with video analysis workflow
- Improved video-analyzer.py with better progress output

## [1.2.0] - 2025-12-18

### Changed
- Migrated to Claude Code Skills system
- Skills use `SKILL.md` format in `.claude/skills/` directory
- Auto-discovery and invocation based on request context

### Added
- 7 skill configurations:
  - `pine-developer` - Writes production Pine Script v6 code
  - `pine-visualizer` - Breaks down trading ideas into components
  - `pine-debugger` - Adds debugging tools and troubleshooting
  - `pine-backtester` - Implements backtesting and performance metrics
  - `pine-optimizer` - Optimizes performance and user experience
  - `pine-publisher` - Prepares scripts for TradingView publication
  - `pine-manager` - Orchestrates complex multi-step projects

### Removed
- `.claude/agents/` directory (replaced by skills)

## [1.1.0] - 2025-12-15

### Added
- Chained Linear Regression Reversal Strategy
- Market Speedometer indicator
- Midnight VWAP indicator
- Trading Discipline Checklist indicator

## [1.0.0] - 2025-12-01

### Added
- Initial release with 7 specialized Pine Script agents
- Agent-based architecture using `.claude/agents/` directory
- Claude Code hooks for deterministic agent routing
- Pine Script v6 documentation
- Template library for indicators, strategies, and utilities
- YouTube video analysis capability
- File protection system (lock/unlock commands)
- Interactive `start` command
- Example scripts

---

## Version History Summary

| Version | Date | Highlights |
|---------|------|------------|
| 1.4.0 | 2026-04-06 | Codex/OpenAI migration, `.assistant` canonical, `.codex` runtime state |
| 1.3.0 | 2025-12-18 | YouTube video analysis, statusline |
| 1.2.0 | 2025-12-18 | Migrated to Skills system |
| 1.1.0 | 2025-12-15 | New indicators and strategies |
| 1.0.0 | 2025-12-01 | Initial release |
