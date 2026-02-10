#!/bin/bash
PROMPT_FILE="/home/scratticus/.claude/productivity/pending_prompt.txt"

if [ -f "$PROMPT_FILE" ]; then
    cat "$PROMPT_FILE"
    rm "$PROMPT_FILE"
fi
