#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENCODE_DIR="$HOME/.opencode"
PLUGINS_DIR="$OPENCODE_DIR/plugins"
DATA_DIR="$OPENCODE_DIR/productivity"

echo "=== Pomodoro Body Double - OpenCode Installer ==="
echo

# Create directories
echo "Creating directories..."
mkdir -p "$PLUGINS_DIR"
mkdir -p "$DATA_DIR"

# Copy plugin
echo "Installing OpenCode plugin..."
cp "$SCRIPT_DIR/.opencode/plugins/pomodoro.ts" "$PLUGINS_DIR/"

# Create package.json for plugin dependencies
if [ ! -f "$PLUGINS_DIR/package.json" ]; then
    echo "Creating package.json for plugin..."
    cat > "$PLUGINS_DIR/package.json" << 'EOF'
{
  "name": "pomodoro-body-double-plugin",
  "version": "1.0.0",
  "type": "module",
  "dependencies": {
    "@opencode-ai/plugin": "^1.0.0"
  }
}
EOF
    
    # Install npm dependencies
    if command -v npm &> /dev/null; then
        echo "Installing plugin dependencies..."
        (cd "$PLUGINS_DIR" && npm install)
    else
        echo "  WARNING: npm not found. Plugin dependencies not installed."
        echo "  Install Node.js/npm, then run: cd ~/.opencode/plugins && npm install"
    fi
else
    echo "  package.json already exists, skipping npm install"
    echo "  If you have issues, try: cd ~/.opencode/plugins && npm install"
fi

# Copy pomodoro timer
echo "Installing pomodoro timer..."
cp "$SCRIPT_DIR/pomodoro.py" "$DATA_DIR/"

# Copy AGENTS.md (OpenCode's custom instructions)
if [ -f "$OPENCODE_DIR/AGENTS.md" ]; then
    echo "  WARNING: $OPENCODE_DIR/AGENTS.md already exists."
    echo "  The pomodoro AGENTS.md has been saved to $OPENCODE_DIR/AGENTS.pomodoro.md"
    echo "  You'll need to merge it manually into your existing AGENTS.md."
    cp "$SCRIPT_DIR/AGENTS.md" "$OPENCODE_DIR/AGENTS.pomodoro.md"
else
    cp "$SCRIPT_DIR/AGENTS.md" "$OPENCODE_DIR/AGENTS.md"
    echo "  Installed AGENTS.md to $OPENCODE_DIR/"
fi

# Copy global AGENTS.md if it doesn't exist
if [ -f "$HOME/.config/opencode/AGENTS.md" ]; then
    echo "  WARNING: ~/.config/opencode/AGENTS.md already exists."
    echo "  The pomodoro AGENTS.md has been saved to ~/.config/opencode/AGENTS.pomodoro.md"
    cp "$SCRIPT_DIR/AGENTS.md" "$HOME/.config/opencode/AGENTS.pomodoro.md"
else
    mkdir -p "$HOME/.config/opencode"
    cp "$SCRIPT_DIR/AGENTS.md" "$HOME/.config/opencode/AGENTS.md"
    echo "  Installed AGENTS.md to ~/.config/opencode/"
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
last_ack_time: null
meetings: []
next_break_minutes: null
next_work_minutes: null
session_log: {}
start_time: null
suggest_end_after_hours: 9
suggest_end_at_hour: 17.5
task_switch: null
timer_override_minutes: null
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
# Task tracking for body doubling with OpenCode
# OpenCode will help you add your first tasks on startup.

work_tasks: []

fun_productive: []
EOF
fi

if [ ! -f "$DATA_DIR/reminders.yaml" ]; then
    echo "Creating reminders.yaml from example..."
    if [ -f "$SCRIPT_DIR/reminders.yaml.example" ]; then
        cp "$SCRIPT_DIR/reminders.yaml.example" "$DATA_DIR/reminders.yaml"
    else
        cat > "$DATA_DIR/reminders.yaml" << 'EOF'
# Recurring reminders
# Days: daily, mon, tue, wed, thu, fri, sat, sun
# Or an array like [mon, wed, fri]

static_reminders:
  - name: Lunch
    time: "14:00"
    days: daily
    
  - name: Workout
    time: "17:30"
    days: [mon, wed, fri]
EOF
    fi
    echo "  Edit $DATA_DIR/reminders.yaml to set your own reminders."
fi

# Create transient files
echo '[]' > "$DATA_DIR/prompt_queue.json"
touch "$DATA_DIR/acknowledged.txt"

# Configure OpenCode to load the plugin
echo
echo "Configuring OpenCode..."

GLOBAL_CONFIG="$HOME/.config/opencode/opencode.json"
if [ -f "$GLOBAL_CONFIG" ]; then
    echo "  Found existing global opencode.json"
    if grep -q "pomodoro" "$GLOBAL_CONFIG"; then
        echo "  Plugin already registered in global config"
    else
        echo "  Adding pomodoro plugin to global config..."
        # Backup original
        cp "$GLOBAL_CONFIG" "$GLOBAL_CONFIG.bak.$(date +%Y%m%d_%H%M%S)"
        # Add plugin to array using Python (more reliable than sed for JSON)
        python3 << EOF
import json
with open('$GLOBAL_CONFIG', 'r') as f:
    config = json.load(f)
if 'plugin' not in config:
    config['plugin'] = []
if '~/.opencode/plugins/pomodoro' not in config['plugin']:
    config['plugin'].append('~/.opencode/plugins/pomodoro')
with open('$GLOBAL_CONFIG', 'w') as f:
    json.dump(config, f, indent=2)
print('  Plugin added successfully')
EOF
    fi
else
    echo "  No global opencode.json found"
    echo "  Plugin will be loaded from .opencode/plugins/ directory"
fi

if [ -f "$SCRIPT_DIR/opencode.json" ]; then
    echo "  Found opencode.json in repository"
    echo "  The plugin is configured to load from .opencode/plugins/pomodoro"
fi

echo
echo "=== Installation Complete ==="
echo
echo "Dependencies:"
echo "  - Python 3 with PyYAML: pip install pyyaml"
echo "  - Desktop notifications: install libnotify"
echo "    - Arch: sudo pacman -S libnotify"
echo "    - Debian/Ubuntu: sudo apt install libnotify-bin"
echo "    - Fedora: sudo dnf install libnotify"
echo
echo "Next steps:"
echo "  1. Restart OpenCode to load the plugin"
echo "  2. OpenCode will greet you with the startup protocol and help set up tasks"
echo "  3. When ready, start the timer in a separate terminal:"
echo "     python3 ~/.opencode/productivity/pomodoro.py"
echo
echo "Important: Make sure the OpenCode CLI can access npm packages for the plugin."
echo "If you see TypeScript errors, you may need to install @opencode-ai/plugin:"
echo "  cd ~/.opencode/plugins && npm install @opencode-ai/plugin"
echo
