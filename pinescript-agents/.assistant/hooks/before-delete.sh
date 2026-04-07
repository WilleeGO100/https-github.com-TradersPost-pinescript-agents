#!/bin/bash
# Before Delete Hook - Prevents deletion of system files when locked

FILE_PATH="$1"

# Get the absolute path of the project root
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STATE_DIR=".codex"
LEGACY_STATE_DIR=".claude"
LOCK_FILE="$PROJECT_ROOT/$STATE_DIR/.lock_state"
LEGACY_LOCK_FILE="$PROJECT_ROOT/$LEGACY_STATE_DIR/.lock_state"

mkdir -p "$PROJECT_ROOT/$STATE_DIR"
if [ -f "$LEGACY_LOCK_FILE" ] && [ ! -f "$LOCK_FILE" ]; then
    cp "$LEGACY_LOCK_FILE" "$LOCK_FILE"
fi

# Check lock state
LOCK_STATE="unlocked"  # Default to unlocked for development
if [ -f "$LOCK_FILE" ]; then
    LOCK_STATE=$(cat "$LOCK_FILE")
fi

# If system is locked, enforce protection
if [ "$LOCK_STATE" = "locked" ]; then
    # Check if file is in protected area
    RELATIVE_PATH="${FILE_PATH#$PROJECT_ROOT/}"
    
    # Always allow deletions in projects directory
    if [[ "$RELATIVE_PATH" == projects/* ]]; then
        echo "✅ Deleting user file: $RELATIVE_PATH"
    # Block deletion of system files when locked
    else
        echo "🔒 SYSTEM LOCKED: Cannot delete files outside /projects/"
        echo "   Attempted to delete: $RELATIVE_PATH"
        echo "   Use 'unlock' command to enable system modifications"
        echo ""
        echo "   Protected areas:"
        echo "   ❌ System files (docs/, templates/, tools/, examples/)"
        echo "   ❌ Configuration files (.assistant/, .claude/, CODEX.md, CLAUDE.md, README.md)"
        echo "   ✓ User scripts in projects/ can be deleted"
        exit 1  # Block the deletion
    fi
else
    # System is unlocked - show warning for system file deletions
    RELATIVE_PATH="${FILE_PATH#$PROJECT_ROOT/}"
    
    # Warn about critical system files
    if [[ "$RELATIVE_PATH" == .assistant/agents/* ]] || \
       [[ "$RELATIVE_PATH" == .assistant/hooks/* ]] || \
       [[ "$RELATIVE_PATH" == .claude/agents/* ]] || \
       [[ "$RELATIVE_PATH" == .claude/hooks/* ]] || \
       [[ "$RELATIVE_PATH" == docs/* ]] || \
       [[ "$RELATIVE_PATH" == templates/* ]] || \
       [[ "$RELATIVE_PATH" == examples/* ]]; then
        echo "⚠️  Warning: Deleting system file: $RELATIVE_PATH"
        echo "   This could break system functionality. Proceed with caution."
    fi
    
    echo "🔓 System is UNLOCKED - deletion allowed"
fi

exit 0
