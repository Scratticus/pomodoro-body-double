#!/bin/bash
PROMPT_FILE="$HOME/.claude/productivity/pending_prompt.txt"

if [ -f "$PROMPT_FILE" ] && [ -s "$PROMPT_FILE" ]; then
    cat "$PROMPT_FILE"
    rm "$PROMPT_FILE"
fi
