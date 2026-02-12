#!/bin/bash
# Consume stdin (hook input JSON)
INPUT=$(cat)

QUEUE_FILE="$HOME/.claude/productivity/prompt_queue.json"

if [ -f "$QUEUE_FILE" ]; then
    PROMPTS=$(python3 -c "
import json
try:
    with open('$QUEUE_FILE') as f:
        q = json.load(f)
    undelivered = [e for e in q if not e.get('delivered')]
    if undelivered:
        for e in undelivered:
            e['delivered'] = True
        with open('$QUEUE_FILE', 'w') as f:
            json.dump(q, f)
        msgs = [f\"[{e['type']}] {e['prompt']}\" for e in undelivered]
        print(' | '.join(msgs))
except Exception:
    pass
" 2>/dev/null)
    if [ -n "$PROMPTS" ]; then
        # Detect hook event type from stdin
        EVENT_NAME=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    # PostToolUse has 'tool_name', UserPromptSubmit has 'user_message'
    if 'tool_name' in data:
        print('PostToolUse')
    else:
        print('UserPromptSubmit')
except:
    print('UserPromptSubmit')
" 2>/dev/null)

        # Output structured JSON for Claude Code to surface
        python3 -c "
import json, sys
msg = sys.argv[1]
event = sys.argv[2]
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': event,
        'additionalContext': msg
    }
}))
" "$PROMPTS" "$EVENT_NAME"
    fi
fi
