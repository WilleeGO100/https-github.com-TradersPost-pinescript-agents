# Pine Script Assistant - Onboarding Process

## Automatic Onboarding Flow

### 1. First Launch Detection
When the assistant starts, the startup hook checks for `.codex/.onboarding_complete` (with fallback to legacy `.claude/.onboarding_complete`):
- **Not found** → First-time user → Show full onboarding
- **Found** → Returning user → Show brief status

### 2. First-Time User Experience

```
🚀 PINE SCRIPT DEVELOPMENT ASSISTANT INITIALIZING...
==================================================

👋 Welcome to Pine Script Development Assistant!

This appears to be your first time using this system.
Let me help you get started...

📋 QUICK SETUP CHECKLIST:
✓ 7 specialized playbooks loaded
✓ Pine Script v6 documentation ready
✓ Video analysis tools available
✓ Template library loaded

🎯 HOW TO GET STARTED:

1. SIMPLE REQUEST:
   Just tell me what you want to build:
   - "Create an RSI indicator"
   - "Build a moving average crossover strategy"
   - "Make a volume profile indicator"

2. FROM A VIDEO:
   Share a YouTube video about a strategy:
   - "Analyze this video: [YouTube URL]"
   - "./analyze-video.sh [YouTube URL]"

3. COMPLEX REQUEST:
   Describe your unique requirements:
   - "I need a pairs trading strategy for crypto"
   - "Build a market profile with delta analysis"

Ready to create your first Pine Script? Just tell me what you need!
```

### 3. Returning User Experience

```
✅ Pine Script Development Assistant Ready!

📁 You have 3 Pine Script project(s):
  - rsi-divergence-indicator.pine
  - ma-crossover-strategy.pine
  - volume-profile-indicator.pine

💡 Quick Actions:
  • Create new script: "Create a [type] indicator/strategy"
  • Analyze video: "Analyze [YouTube URL]"
  • Get help: "/help"

What would you like to build today?
```

### 4. Assistant Response Pattern

#### For First-Time Users:
```
Great! I see this is your first time using the Pine Script Development Assistant. 
I'm ready to help you create professional TradingView indicators and strategies.

What would you like to create? You can:
- Describe what you want to build
- Share a YouTube video to analyze
- Or just tell me your trading idea!
```

#### For Returning Users:
```
Welcome back! I see you have [N] projects already. 
What would you like to work on today?
```

### 5. Immediate Action Ready

After onboarding, the system is ready for immediate action:
- User can start with any request
- No additional setup needed
- All role playbooks available
- Templates loaded
- Documentation ready

## State Management

### Files Created During Onboarding:

1. **`.codex/.onboarding_complete`**
   - Marker file indicating onboarding shown
   - Created after first run

2. **`.codex/.state.json`**
   ```json
   {
     "onboarded": true,
     "first_run": "2024-01-15T10:30:00Z",
     "version": "1.0.0",
     "projects_created": 0,
     "last_project": null
   }
   ```

3. **`projects/blank.pine`**
   - Created if missing
   - Ready for first project

## Quick Start Examples

After onboarding, users can immediately:

### Example 1: Direct Request
**User**: "Create an RSI indicator"
**System**: Immediately starts project → No additional questions needed

### Example 2: Video Analysis
**User**: "Analyze this: youtube.com/watch?v=..."
**System**: Runs video analyzer → Shows summary → Proceeds with development

### Example 3: Complex Request
**User**: "I need a market profile"
**System**: Enters discovery mode → Asks clarifying questions → Implements

## Ensuring Onboarding Runs

The startup hook is registered in `.claude/hooks.json`:
```json
{
  "startup": ".claude/hooks/startup.sh",
  ...
}
```

This ensures:
1. Hook runs when the assistant initializes
2. Onboarding shows on first use
3. Status shows on return visits
4. System is always ready

## Testing Onboarding

To test the onboarding process:
1. Delete `.codex/.onboarding_complete`
2. Restart the assistant session
3. Onboarding should appear

To simulate returning user:
1. Ensure `.codex/.onboarding_complete` exists
2. Restart the assistant session
3. Brief status should appear
