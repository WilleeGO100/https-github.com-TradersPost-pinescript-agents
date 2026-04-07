#!/bin/bash
# PineScript Agents - Statusline
# by TradersPost

input=$(cat)

PROJECT_DIR=$(echo "$input" | jq -r '.workspace.project_dir // ""')

# Check for active video processing status first
STATUS_FILE="$PROJECT_DIR/.codex/.video_status"
LEGACY_STATUS_FILE_ASSISTANT="$PROJECT_DIR/.assistant/.video_status"
LEGACY_STATUS_FILE_CLAUDE="$PROJECT_DIR/.claude/.video_status"
if [ -f "$STATUS_FILE" ]; then
    VIDEO_STATUS=$(cat "$STATUS_FILE" 2>/dev/null)
    if [ -n "$VIDEO_STATUS" ]; then
        echo "$VIDEO_STATUS"
        exit 0
    fi
fi

# Backward compatibility with legacy state location
if [ -f "$LEGACY_STATUS_FILE_ASSISTANT" ]; then
    VIDEO_STATUS=$(cat "$LEGACY_STATUS_FILE_ASSISTANT" 2>/dev/null)
    if [ -n "$VIDEO_STATUS" ]; then
        echo "$VIDEO_STATUS"
        exit 0
    fi
fi

if [ -f "$LEGACY_STATUS_FILE_CLAUDE" ]; then
    VIDEO_STATUS=$(cat "$LEGACY_STATUS_FILE_CLAUDE" 2>/dev/null)
    if [ -n "$VIDEO_STATUS" ]; then
        echo "$VIDEO_STATUS"
        exit 0
    fi
fi

# Get version from package.json
VERSION="1.4.0"
if [ -f "$PROJECT_DIR/package.json" ]; then
    VERSION=$(cat "$PROJECT_DIR/package.json" | jq -r '.version // "1.4.0"')
fi

# Count projects (pine files excluding blank.pine)
PROJECT_COUNT=$(ls -1 "$PROJECT_DIR/projects/"*.pine 2>/dev/null | grep -v blank.pine | wc -l | tr -d ' ')

# Count skills
if [ -d "$PROJECT_DIR/.assistant/skills/" ]; then
    SKILL_COUNT=$(ls -1d "$PROJECT_DIR/.assistant/skills/"*/ 2>/dev/null | wc -l | tr -d ' ')
else
    SKILL_COUNT=$(ls -1d "$PROJECT_DIR/.claude/skills/"*/ 2>/dev/null | wc -l | tr -d ' ')
fi

echo "PineScript Agents v$VERSION | 🗀  $PROJECT_COUNT projects | ⚡︎$SKILL_COUNT playbooks | by TradersPost"
