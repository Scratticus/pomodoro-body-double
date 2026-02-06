#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
HOOKS_DIR="$CLAUDE_DIR/hooks"
DATA_DIR="$CLAUDE_DIR/productivity"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"

echo "=== Pomodoro Body Double Installer ==="
echo

# Create directories
echo "Creating directories..."
mkdir -p "$HOOKS_DIR"
mkdir -p "$DATA_DIR"

# Copy hook script
echo "Installing hook script..."
cp "$SCRIPT_DIR/hooks/pomodoro-hook.sh" "$HOOKS_DIR/"
chmod +x "$HOOKS_DIR/pomodoro-hook.sh"

# Copy pomodoro timer
echo "Installing pomodoro timer..."
cp "$SCRIPT_DIR/pomodoro.py" "$DATA_DIR/"

# Copy CLAUDE.md (user's global instructions)
if [ -f "$CLAUDE_DIR/CLAUDE.md" ]; then
    echo "  WARNING: $CLAUDE_DIR/CLAUDE.md already exists."
    echo "  The pomodoro CLAUDE.md has been saved to $CLAUDE_DIR/CLAUDE.pomodoro.md"
    echo "  You'll need to merge it manually into your existing CLAUDE.md."
    cp "$SCRIPT_DIR/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.pomodoro.md"
else
    cp "$SCRIPT_DIR/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md"
    echo "  Installed CLAUDE.md to $CLAUDE_DIR/"
fi

# Initialize data files (only if they don't exist)
if [ ! -f "$DATA_DIR/session.yaml" ]; then
    echo "Creating session.yaml..."
    cat > "$DATA_DIR/session.yaml" << 'EOF'
chore_timers: []
completed_items: []
current_task: null
current_task_type: null
fun_sessions_completed: 0
session_log: {}
start_time: null
suggest_end_after_hours: 9
suggest_end_at_hour: 17.5
work_sessions_completed: 0
EOF
fi

if [ ! -f "$DATA_DIR/log.yaml" ]; then
    echo "Creating log.yaml..."
    cat > "$DATA_DIR/log.yaml" << 'EOF'
projects: {}
EOF
fi

if [ ! -f "$DATA_DIR/tasks.yaml" ]; then
    echo "Creating tasks.yaml..."
    cat > "$DATA_DIR/tasks.yaml" << 'EOF'
# Productivity Tasks
# Task tracking for body doubling with Claude
# Claude will help you add your first tasks on startup.

work_tasks: []

fun_productive: []
EOF
fi

if [ ! -f "$DATA_DIR/reminders.yaml" ]; then
    echo "Creating reminders.yaml from example..."
    cp "$SCRIPT_DIR/reminders.yaml.example" "$DATA_DIR/reminders.yaml"
    echo "  Edit $DATA_DIR/reminders.yaml to set your own reminders."
fi

# Create transient files
touch "$DATA_DIR/pending_prompt.txt"
touch "$DATA_DIR/acknowledged.txt"

# Configure Claude Code settings
echo
echo "Configuring Claude Code hooks..."
if [ -f "$SETTINGS_FILE" ]; then
    if grep -q "pomodoro-hook.sh" "$SETTINGS_FILE"; then
        echo "  Hook already configured in settings.json"
    else
        echo "  WARNING: $SETTINGS_FILE exists but pomodoro hook not found."
        echo "  Please add the following to your settings.json hooks section:"
        echo
        echo '  "UserPromptSubmit": ['
        echo '    {'
        echo '      "matcher": "",'
        echo '      "hooks": ['
        echo '        {'
        echo '          "type": "command",'
        echo "          \"command\": \"$HOOKS_DIR/pomodoro-hook.sh\","
        echo '          "timeout": 5'
        echo '        }'
        echo '      ]'
        echo '    }'
        echo '  ]'
        echo
        echo "  And optionally add a SessionStart hook (see README.md)."
    fi
else
    cat > "$SETTINGS_FILE" << EOF
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "echo 'SESSION START: Run startup protocol - request read/write for ~/.claude/hooks/ directory, clear ~/.claude/productivity/pending_prompt.txt, and echo to ~/.claude/productivity/acknowledged.txt to establish permissions.'"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "$HOOKS_DIR/pomodoro-hook.sh",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
EOF
    echo "  Created settings.json with hook configuration"
fi

echo
echo "=== Installation Complete ==="
echo
echo "Dependencies:"
echo "  - Python 3 with PyYAML: pip install pyyaml"
echo "  - Desktop notifications: install libnotify (e.g. 'pacman -S libnotify' on Arch,"
echo "    'apt install libnotify-bin' on Debian/Ubuntu)"
echo
echo "Next steps:"
echo "  1. Restart Claude Code to load the hook configuration"
echo "  2. Claude will greet you with the startup protocol and help set up tasks"
echo "  3. When ready, start the timer in a separate terminal:"
echo "     python3 ~/.claude/productivity/pomodoro.py"
echo
