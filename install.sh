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

# Initialize data files
if [ ! -f "$DATA_DIR/session.yaml" ]; then
    echo "Creating session.yaml..."
    cat > "$DATA_DIR/session.yaml" << 'EOF'
work_sessions_completed: 0
fun_sessions_completed: 0
current_task: null
current_task_type: null
start_time: null
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

# Configure Claude Code settings
echo "Configuring Claude Code hooks..."
if [ -f "$SETTINGS_FILE" ]; then
    # Check if hook already configured
    if grep -q "pomodoro-hook.sh" "$SETTINGS_FILE"; then
        echo "  Hook already configured in settings.json"
    else
        echo "  WARNING: settings.json exists but hook not found."
        echo "  Please manually add the hook configuration."
        echo "  See README.md for details."
    fi
else
    # Create new settings file
    cat > "$SETTINGS_FILE" << EOF
{
  "hooks": {
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
echo "Next steps:"
echo "1. Copy CLAUDE.md to your project or ~/.claude/ for Claude instructions"
echo "2. Restart Claude Code to load the hook configuration"
echo "3. Claude will help you set up your first tasks on startup"
echo
