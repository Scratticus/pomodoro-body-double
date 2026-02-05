#!/bin/bash
# Pomodoro hook for Claude Code
# Injects pending prompts from the pomodoro timer into Claude's context

PRODUCTIVITY_DIR="${POMODORO_DIR:-$HOME/.claude/productivity}"
PROMPT_FILE="$PRODUCTIVITY_DIR/pending_prompt.txt"

if [ -f "$PROMPT_FILE" ]; then
    cat "$PROMPT_FILE"
    rm "$PROMPT_FILE"
fi
