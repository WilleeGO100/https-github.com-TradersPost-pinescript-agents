#!/bin/bash
# Pine Script Skills Router Hook
# This hook runs before processing user prompts to provide feedback
# Note: Skills are guidance playbooks - this hook provides informational output

# Check if the prompt mentions specific keywords
PROMPT="$1"
PROMPT_LOWER=$(echo "$PROMPT" | tr '[:upper:]' '[:lower:]')
STATE_DIR=".codex"
LEGACY_STATE_DIR=".claude"
LOCK_FILE="$STATE_DIR/.lock_state"
LEGACY_LOCK_FILE="$LEGACY_STATE_DIR/.lock_state"

mkdir -p "$STATE_DIR"
if [ -f "$LEGACY_LOCK_FILE" ] && [ ! -f "$LOCK_FILE" ]; then
    cp "$LEGACY_LOCK_FILE" "$LOCK_FILE"
fi

# Check for lock/unlock commands
if [[ "$PROMPT_LOWER" == "lock" ]]; then
    echo "locked" > "$LOCK_FILE"
    echo "🔒 SYSTEM LOCKED - File protection enabled"
    echo ""
    echo "Protected areas:"
    echo "  ❌ System files (docs/, templates/, tools/, examples/)"
    echo "  ❌ Configuration (.assistant/skills/, .assistant/hooks/, .claude/ legacy)"
    echo "  ❌ Root files (README.md, CODEX.md, CLAUDE.md, package.json)"
    echo ""
    echo "Writable areas:"
    echo "  ✓ /projects/ - Your Pine Scripts"
    echo "  ✓ State files (.lock_state, .onboarding_complete)"
    echo ""
    echo "Use 'unlock' command to disable protection"
    exit 0
fi

if [[ "$PROMPT_LOWER" == "unlock" ]]; then
    echo "unlocked" > "$LOCK_FILE"
    echo "🔓 SYSTEM UNLOCKED - All files can be modified"
    echo ""
    echo "⚠️  Warning: System files can now be changed"
    echo "This mode is intended for development only"
    echo ""
    echo "Use 'lock' command to enable protection"
    exit 0
fi

if [[ "$PROMPT_LOWER" == "status" ]]; then
    if [ -f "$LOCK_FILE" ]; then
        STATE=$(cat "$LOCK_FILE")
    else
        STATE="unlocked"
    fi

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🔐 System Lock Status: $(echo $STATE | tr '[:lower:]' '[:upper:]')"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    if [ "$STATE" = "locked" ]; then
        echo "🔒 Protection: ENABLED"
        echo "   • System files are protected"
        echo "   • Only /projects/ can be modified"
        echo "   • Use 'unlock' to disable"
    else
        echo "🔓 Protection: DISABLED"
        echo "   • All files can be modified"
        echo "   • Development mode active"
        echo "   • Use 'lock' to enable protection"
    fi

    # Count projects
    PROJECT_COUNT=$(ls -1 projects/*.pine 2>/dev/null | grep -v blank.pine | wc -l)
    echo ""
    echo "📁 Projects: $PROJECT_COUNT Pine Script(s) in /projects/"

    # List available skills
    echo ""
    echo "🎯 Available Skills (auto-activated):"
    if [ -d ".assistant/skills" ]; then
        for skill_dir in .assistant/skills/*/; do
            if [ -f "${skill_dir}SKILL.md" ]; then
                skill_name=$(basename "$skill_dir")
                echo "   • $skill_name"
            fi
        done
    elif [ -d ".claude/skills" ]; then
        for skill_dir in .claude/skills/*/; do
            if [ -f "${skill_dir}SKILL.md" ]; then
                skill_name=$(basename "$skill_dir")
                echo "   • $skill_name"
            fi
        done
    fi

    exit 0
fi

# Check for single-word commands first
if [[ "$PROMPT_LOWER" == "start" ]]; then
    echo "🚀 Running interactive start command..."
    ./start
    exit 0
fi

if [[ "$PROMPT_LOWER" == "help" ]]; then
    echo "📚 Pine Script Assistant Commands:"
    echo ""
    echo "Core Commands:"
    echo "  • start - Interactive setup guide"
    echo "  • help - This help message"
    echo "  • status - Show system status and lock state"
    echo ""
    echo "Protection Commands:"
    echo "  • lock - Enable file protection (only /projects/ writable)"
    echo "  • unlock - Disable protection (development mode)"
    echo ""
    echo "Creation Commands:"
    echo "  • analyze [URL] - Analyze YouTube video"
    echo "  • create [description] - Create Pine Script"
    echo "  • examples - Show available examples"
    echo "  • templates - Show quick templates"
    echo ""
    echo "🎯 Skills (auto-activated based on request):"
    echo "  • pine-visualizer - Breaks down trading concepts"
    echo "  • pine-developer - Writes Pine Script code"
    echo "  • pine-debugger - Troubleshoots issues"
    echo "  • pine-backtester - Adds performance metrics"
    echo "  • pine-optimizer - Improves performance/UX"
    echo "  • pine-manager - Orchestrates complex projects"
    echo "  • pine-publisher - Prepares for publication"
    exit 0
fi

if [[ "$PROMPT_LOWER" == "examples" ]]; then
    echo "📁 Available example scripts:"
    ls -1 examples/*/*.pine 2>/dev/null | sed 's/examples\//  /'
    exit 0
fi

if [[ "$PROMPT_LOWER" == "templates" ]]; then
    echo "🎯 Quick templates available:"
    echo "  • RSI divergence indicator"
    echo "  • Moving average crossover strategy"
    echo "  • Bollinger Band squeeze"
    echo "  • Volume profile"
    echo "  • MACD with alerts"
    echo ""
    echo "Tell Codex which template you want!"
    exit 0
fi

# Function to show skill info (informational only - skills auto-activate)
show_skill_info() {
    echo "🎯 Pine Script Skills: Detected $1 request"
    echo "   Relevant skill: $2 (will auto-activate)"
    echo "---"
}

# Check for project initialization
if [[ "$PROMPT_LOWER" == *"create"* ]] || [[ "$PROMPT_LOWER" == *"build"* ]] || [[ "$PROMPT_LOWER" == *"make"* ]] || [[ "$PROMPT_LOWER" == *"new"* ]]; then
    if [[ "$PROMPT_LOWER" == *"indicator"* ]] || [[ "$PROMPT_LOWER" == *"strategy"* ]] || [[ "$PROMPT_LOWER" == *"script"* ]]; then
        show_skill_info "new Pine Script project" "pine-manager / pine-developer"

        # Check if blank.pine exists and automatically prepare for renaming
        if [ -f "$(dirname "$0")/../../projects/blank.pine" ]; then
            echo "📝 Ready to start new project - blank.pine will be automatically renamed"
            echo "🔄 A fresh blank.pine will be created for future projects"
        fi
    fi
fi

# Check for debugging requests
if [[ "$PROMPT_LOWER" == *"debug"* ]] || [[ "$PROMPT_LOWER" == *"error"* ]] || [[ "$PROMPT_LOWER" == *"fix"* ]] || [[ "$PROMPT_LOWER" == *"issue"* ]] || [[ "$PROMPT_LOWER" == *"problem"* ]]; then
    show_skill_info "debugging" "pine-debugger"
fi

# Check for optimization requests
if [[ "$PROMPT_LOWER" == *"optimize"* ]] || [[ "$PROMPT_LOWER" == *"faster"* ]] || [[ "$PROMPT_LOWER" == *"improve"* ]] || [[ "$PROMPT_LOWER" == *"performance"* ]]; then
    show_skill_info "optimization" "pine-optimizer"
fi

# Check for backtesting requests
if [[ "$PROMPT_LOWER" == *"backtest"* ]] || [[ "$PROMPT_LOWER" == *"test"* ]] || [[ "$PROMPT_LOWER" == *"metrics"* ]] || [[ "$PROMPT_LOWER" == *"performance"* ]]; then
    if [[ "$PROMPT_LOWER" == *"strategy"* ]] || [[ "$PROMPT_LOWER" == *"profit"* ]] || [[ "$PROMPT_LOWER" == *"win rate"* ]]; then
        show_skill_info "backtesting" "pine-backtester"
    fi
fi

# Check for publishing requests
if [[ "$PROMPT_LOWER" == *"publish"* ]] || [[ "$PROMPT_LOWER" == *"share"* ]] || [[ "$PROMPT_LOWER" == *"release"* ]] || [[ "$PROMPT_LOWER" == *"community"* ]]; then
    show_skill_info "publishing preparation" "pine-publisher"
fi

# Check for YouTube video URLs or analyze command
if [[ "$PROMPT_LOWER" == *"youtube.com"* ]] || [[ "$PROMPT_LOWER" == *"youtu.be"* ]] || [[ "$PROMPT_LOWER" == *"analyze"* ]]; then
    if [[ "$PROMPT_LOWER" == *"youtube.com/watch"* ]] || [[ "$PROMPT_LOWER" == *"youtu.be/"* ]]; then
        echo "🎥 YouTube Video Detected!"
        echo "The pine-visualizer skill will:"
        echo "  1. Extract and analyze the video transcript"
        echo "  2. Identify trading concepts and strategies"
        echo "  3. Create a Pine Script specification"
        echo "  4. Coordinate implementation"
        echo "---"
        show_skill_info "YouTube video analysis" "pine-visualizer"
    elif [[ "$PROMPT_LOWER" == "analyze "* ]]; then
        echo "📊 Analysis request detected"
        show_skill_info "video/content analysis" "pine-visualizer"
    fi
fi

# Check for conceptual/planning requests
if [[ "$PROMPT_LOWER" == *"how"* ]] || [[ "$PROMPT_LOWER" == *"plan"* ]] || [[ "$PROMPT_LOWER" == *"design"* ]] || [[ "$PROMPT_LOWER" == *"concept"* ]]; then
    if [[ "$PROMPT_LOWER" == *"indicator"* ]] || [[ "$PROMPT_LOWER" == *"strategy"* ]]; then
        show_skill_info "conceptual planning" "pine-visualizer"
    fi
fi

# Complex project detection (multiple requirements)
COMPLEXITY_SCORE=0
[[ "$PROMPT_LOWER" == *"and"* ]] && ((COMPLEXITY_SCORE++))
[[ "$PROMPT_LOWER" == *"with"* ]] && ((COMPLEXITY_SCORE++))
[[ "$PROMPT_LOWER" == *"also"* ]] && ((COMPLEXITY_SCORE++))
[[ "$PROMPT_LOWER" == *"multi"* ]] && ((COMPLEXITY_SCORE++))
[[ "$PROMPT_LOWER" == *"complete"* ]] && ((COMPLEXITY_SCORE++))
[[ "$PROMPT_LOWER" == *"full"* ]] && ((COMPLEXITY_SCORE++))

if [ $COMPLEXITY_SCORE -ge 2 ]; then
    echo "📊 Complex project detected (complexity score: $COMPLEXITY_SCORE)"
    show_skill_info "complex multi-part project" "pine-manager"
fi

exit 0
