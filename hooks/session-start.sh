#!/bin/bash
# SessionStart hook — runs when Claude Code launches.
# Detects whether the pomodoro process is running and injects a one-off
# startup message accordingly. Independent from the queue-driven
# pomodoro-hook.sh; queued prompts are still delivered separately on
# UserPromptSubmit / PostToolUse.

if pgrep -f "pomodoro.py" > /dev/null 2>&1 \
   || pgrep -f "adapter_claude.py" > /dev/null 2>&1; then
    MSG="[session_start] Pomodoro body double is running. Queued prompts will surface as you work."
else
    MSG="[session_start] Pomodoro body double is NOT running. Ask the user if they want to use it this session. If yes, tell them to start it in a separate terminal: python3 ~/.claude/productivity/pomodoro.py — and wait for the resulting session_start prompt before writing any ack. If no, proceed normally and do not mention the timer."
fi

MSG="$MSG" python3 -c "
import json, os
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'SessionStart',
        'additionalContext': os.environ['MSG']
    }
}))
"
